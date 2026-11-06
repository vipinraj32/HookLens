"""Local static scan: project -> imports -> solc -> hook detection -> HookLens analyzers -> report.

The analyzers are the same ones the HookLens API runs on deployed hooks
(`hooklens.analyzers.runner.default_analyzers`). In source mode they receive a context built from
the locally compiled AST instead of on-chain state; nothing here re-implements a rule.

The result is one canonical report document (a JSON-serialisable dict following
`schema/report-v1.schema.json`). JSON, SARIF, HTML and CI summaries are all rendered from it.
"""

from __future__ import annotations

import platform
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from hooklens import __version__
from hooklens.analyzers.bytecode import analyze_bytecode
from hooklens.analyzers.context import AnalysisContext
from hooklens.analyzers.core import SEVERITY_ORDER, Collector, FindingItem, Severity
from hooklens.analyzers.permissions import from_flags, summarize
from hooklens.analyzers.rules.permissions_rules import declared_permissions
from hooklens.analyzers.runner import ANALYZER_VERSION, default_analyzers, run_analyzers
from hooklens.analyzers.source.ast_index import AstIndex
from hooklens.analyzers.source.bundle import SourceBundle
from hooklens.config import ScanConfig
from hooklens.errors import AnalysisError, ConfigError
from hooklens.evm import hex_to_bytes, keccak_hex
from hooklens.local import compiler
from hooklens.local.detect import ContractInfo, detect
from hooklens.local.project import Project, closure, discover_project, exclusion_patterns, list_sources, load_tree
from hooklens.rules_catalog import rule_info, rule_key

SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = (
    "https://github.com/vipinraj32/HookLens/blob/main/packages/hooklens/src/hooklens/schema/report-v1.schema.json"
)
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 3, "informational": 4}

SCOPE_STATEMENT = (
    "Static source analysis of the selected Solidity contracts. Findings describe code patterns and the "
    "conditions under which they matter; they are not confirmed exploits. No transaction was executed, "
    "no chain state was read, and the absence of findings does not mean a hook is safe."
)
LIMITATIONS = [
    "Static analysis only: no fork execution was performed. Execution-tested results come from `hooklens lab` "
    "(HookLens fork simulation against a deployed hook) and are reported separately.",
    "Deployed-state facts (current owner, oracle address, proxy admin, pool fees, permission address bits) are "
    "unknown to a source scan.",
    "Analyzers follow the Solidity AST of the compiled contract and its inheritance chain; behaviour that depends "
    "on external contracts is reported as a dependency, not evaluated.",
    "Inline assembly is inventoried but not symbolically executed.",
    "No findings does not mean the hook is safe.",
]

Progress = Callable[[str, str], None]


@dataclass
class SourceInfo:
    kind: str  # local | github
    target: str
    url: str | None = None
    ref: str | None = None
    commit: str | None = None
    branch: str | None = None
    subpath: str | None = None
    display_name: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class _LocalProxy:
    is_proxy: bool = False
    kind: str | None = None
    implementation: str | None = None
    admin: str | None = None
    beacon: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    unresolved_reason: str | None = None


@dataclass
class _LocalSource:
    bundle: SourceBundle
    contract_name: str
    compiler_version: str
    bytecode_match: str = "not-applicable"
    notes: list[str] = field(default_factory=list)


@dataclass
class _LocalResolved:
    """Stand-in for the API's ResolvedContract: a contract compiled from local source."""

    source: _LocalSource
    logic_code: bytes
    runtime_code_hash: str | None
    source_status: str = "local-source"
    implementation_code_hash: str | None = None
    proxy: _LocalProxy = field(default_factory=_LocalProxy)
    notes: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _noop(_stage: str, _msg: str) -> None:
    return None


def run_scan(
    target: Any,
    cfg: ScanConfig,
    source: SourceInfo,
    *,
    boundary: Any = None,
    progress: Progress = _noop,
) -> dict[str, Any]:
    started, t0 = _now(), time.perf_counter()
    project = discover_project(target, cfg, boundary=boundary)
    progress(
        "project",
        f"{project.kind} project at {project.root} (scan paths: "
        + ", ".join(project.rel(p) or "." for p in project.scan_paths)
        + ")",
    )
    files, excluded = list_sources(project, cfg)
    if not files:
        raise AnalysisError(
            "No Solidity source files to scan under "
            + ", ".join(str(p) for p in project.scan_paths)
            + (f" ({len(excluded)} excluded by patterns)" if excluded else ""),
            hint="Point the scan at your contracts directory, or adjust --exclude / --no-default-excludes.",
        )
    progress("sources", f"{len(files)} Solidity file(s) selected, {len(excluded)} excluded")

    tree = load_tree(project, files)
    bad_units = {e["unit"] for e in tree.errors}
    blocked = {f: sorted(closure(tree, f) & bad_units) for f in files}
    blocked = {f: v for f, v in blocked.items() if v}
    compilable = [f for f in files if f not in blocked]
    import_errors = [{**e, "hint": _import_hint(e["unit"], project)} for e in tree.errors]
    if blocked:
        progress("imports", f"{len(tree.errors)} unresolved import(s); {len(blocked)} file(s) cannot be compiled")
    if not compilable:
        raise AnalysisError(
            "Every selected file depends on an import that could not be resolved: "
            + "; ".join(f"'{e['unit']}' (imported by {e['imported_by']}): {e['reason']}" for e in tree.errors[:5]),
            hint=_import_hint(tree.errors[0]["unit"], project),
        )

    solc = compiler.Solc(cfg.allow_solc_download)
    versions = compiler.choose_versions(project, tree, compilable, solc)
    groups: list[compiler.CompileGroup] = []
    for version, targets in sorted(versions.items()):
        g = compiler.CompileGroup(version, targets, compiler._default_evm(version, project.evm_version))
        progress("compile", f"solc {version} ({g.evm_version or 'default EVM'}): {len(targets)} file(s)")
        compiler.compile_group(project, tree, g, solc, cfg.compile_timeout_s)
        if g.status == "failed":
            progress("compile", f"solc {version}: compilation failed ({len(g.errors)} error(s))")
        groups.append(g)

    discovered: list[ContractInfo] = []
    group_of: dict[tuple[str, str], compiler.CompileGroup] = {}
    for g in groups:
        if g.status != "compiled":
            continue
        for ci in detect(g.output, tree.sources, g.targets):
            ci.group = g.version
            discovered.append(ci)
            group_of[(ci.file, ci.name)] = g

    # ---------------------------------------------------------------- selection
    if cfg.contracts:
        wanted = set(cfg.contracts)
        chosen = [c for c in discovered if c.name in wanted and c.kind not in ("interface", "library")]
        missing = wanted - {c.name for c in chosen}
        if missing:
            failed_any = any(g.status == "failed" for g in groups) or blocked
            raise (AnalysisError if failed_any else ConfigError)(
                "Requested contract(s) not found among compiled, non-interface contracts: "
                + ", ".join(sorted(missing)),
                hint="Check the name, the scan paths and exclusions."
                + (" Some files failed to compile; see the errors above." if failed_any else ""),
            )
    else:
        kinds = {"hook", "candidate"} | ({"mock"} if cfg.include_mocks else set())
        chosen = [c for c in discovered if c.kind in kinds]
    progress("detect", f"{len(discovered)} contract(s) discovered, {len(chosen)} selected for analysis")

    # ---------------------------------------------------------------- bytecode (phase 2)
    for g in groups:
        sel = [(c.file, c.name) for c in chosen if group_of.get((c.file, c.name)) is g]
        if sel:
            compiler.generate_bytecode(project, tree, g, solc, sel, cfg.compile_timeout_s)

    # ---------------------------------------------------------------- analysis
    wanted_ids = set(cfg.effective_analyzers())
    analyzers = [a for a in default_analyzers() if a.analyzer_id in wanted_ids]
    contracts_out: list[dict[str, Any]] = []
    findings_out: list[dict[str, Any]] = []
    analyzer_errors = 0
    chosen_keys = {(c.file, c.name) for c in chosen}
    for c in discovered:
        rec = c.to_dict() | {"analyzed": False, "skip_reason": None, "repo_path": project.repo_path(c.file)}
        if (c.file, c.name) not in chosen_keys:
            rec["skip_reason"] = _skip_reason(c, cfg)
            contracts_out.append(rec)
            continue
        progress("analyze", f"{c.name} ({c.file})")
        g = group_of[(c.file, c.name)]
        res, extra = _analyze(project, tree.sources, g, c, analyzers)
        analyzer_errors += sum(1 for r in res.runs if r["status"] == "error")
        recs = [_finding_record(f, res.collector, c, project, files) for f in res.collector.findings.values()]
        recs.sort(key=lambda r: (SEVERITY_RANK[r["severity"]], r["rule"], r["id"]))
        findings_out.extend(recs)
        rec.update(extra)
        rec["analyzed"] = True
        rec["analyzer_runs"] = res.runs
        rec["finding_ids"] = [r["id"] for r in recs]
        contracts_out.append(rec)

    # ---------------------------------------------------------------- summary
    threshold = SEVERITY_RANK[cfg.severity_threshold]
    reported = [f for f in findings_out if SEVERITY_RANK[f["severity"]] <= threshold]
    counts = {s: 0 for s in ("critical", "high", "medium", "low", "informational", "unknown")}
    for f in findings_out:
        counts[f["severity"]] += 1
    highest = min((f["severity"] for f in findings_out), key=lambda s: SEVERITY_RANK[s], default=None)
    failed_groups = [g for g in groups if g.status == "failed"]
    analysed = sum(1 for c in contracts_out if c["analyzed"])
    problems: list[str] = []
    if blocked:
        problems.append(f"{len(blocked)} file(s) skipped because of unresolved imports")
    if failed_groups:
        problems.append(f"{sum(len(g.targets) for g in failed_groups)} file(s) failed to compile")
    if analyzer_errors:
        problems.append(f"{analyzer_errors} analyzer run(s) crashed")
    if analysed == 0 and problems:
        status = "failed"
    elif problems:
        status = "partial"
    elif analysed == 0:
        status = "no-hooks"
    else:
        status = "completed"

    report: dict[str, Any] = {
        "$schema": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "tool": {
            "name": "hooklens",
            "version": __version__,
            "analyzer_version": ANALYZER_VERSION,
            "python": platform.python_version(),
            "information_uri": "https://github.com/vipinraj32/HookLens",
        },
        "scan": {
            "id": str(uuid.uuid4()),
            "kind": "static-source",
            "status": status,
            "problems": problems,
            "started_at": started,
            "finished_at": _now(),
            "duration_ms": int((time.perf_counter() - t0) * 1000),
            "source": source.to_dict(),
            "project": {
                "root": _display_root(project, source),
                "kind": project.kind,
                "scan_paths": [project.rel(p) or "." for p in project.scan_paths],
                "remappings": [r.to_dict() for r in project.remappings],
                "notes": project.notes,
            },
            "configuration": {
                "config_file": _display_path(cfg.config_file, project, source),
                "ignored_config_keys": cfg.ignored_keys,
                "exclude_patterns": exclusion_patterns(cfg),
                "contracts": cfg.contracts,
                "include_mocks": cfg.include_mocks,
                "analyzers": [a.analyzer_id for a in analyzers],
                "severity_threshold": cfg.severity_threshold,
                "sarif_min_severity": cfg.sarif_min_severity,
                "fail_on": cfg.fail_on,
                "solc": project.solc,
                "evm_version": project.evm_version,
                "allow_solc_download": cfg.allow_solc_download,
            },
        },
        "files": {
            "selected": files,
            "excluded": excluded,
            "unresolved_imports": import_errors,
            "blocked_by_imports": [{"file": f, "missing": v} for f, v in blocked.items()],
        },
        "compilation": [g.to_dict() for g in groups],
        "contracts": contracts_out,
        "findings": reported,
        "execution_results": None,
        "summary": {
            "files_selected": len(files),
            "contracts_discovered": len(discovered),
            "hooks": sum(1 for c in discovered if c.kind == "hook"),
            "candidates": sum(1 for c in discovered if c.kind == "candidate"),
            "contracts_analyzed": analysed,
            "findings_total": len(findings_out),
            "findings_reported": len(reported),
            "suppressed_below_threshold": len(findings_out) - len(reported),
            "by_severity": counts,
            "highest_severity": highest,
        },
        "scope": SCOPE_STATEMENT,
        "limitations": LIMITATIONS,
    }
    report["_all_findings"] = findings_out  # internal: used for --fail-on; stripped before writing
    progress("done", f"{status}: {analysed} contract(s) analysed, {len(findings_out)} finding(s)")
    return report


def _display_root(project: Project, source: SourceInfo) -> str:
    if source.kind == "github":
        rel = project.repo_path(".")
        return rel if rel not in (None, ".") else "."
    return str(project.root)


def _display_path(path: str | None, project: Project, source: SourceInfo) -> str | None:
    if path is None:
        return None
    if source.kind == "github":
        try:
            from pathlib import Path

            return Path(path).resolve().relative_to(project.repo_root).as_posix()
        except ValueError:
            return path
    return path


def _import_hint(unit: str, project: Project) -> str:
    head = unit.split("/")[0]
    if head == "lib" or unit.startswith(("@", "forge-std", "solmate", "openzeppelin")) or "/" in unit:
        return (
            "Dependencies are missing. For Foundry projects run `git submodule update --init --recursive` "
            "(or `forge install`); for npm-based projects install node_modules. You can also map a prefix with "
            "--remapping prefix=path."
        )
    return "Check the import path."


def _skip_reason(c: ContractInfo, cfg: ScanConfig) -> str:
    if cfg.contracts:
        return "not requested with --contract"
    return {
        "interface": "interface",
        "library": "library",
        "abstract-hook": "abstract hook base; analysed through concrete hooks that inherit it",
        "mock": "mock / test double (use --include-mocks to analyse)",
        "not-a-hook": "no Uniswap v4 hook indicators",
    }.get(c.kind, c.kind)


def _analyze(
    project: Project, sources: dict[str, str], g: compiler.CompileGroup, c: ContractInfo, analyzers: list[Any]
) -> tuple[Any, dict[str, Any]]:
    out = g.output
    bundle = SourceBundle(
        provider="local-source",
        contract_name=c.name,
        contract_path=c.file,
        compiler_version=g.version,
        sources={u: sources[u] for u in (out.get("sources") or {}) if u in sources},
        output_sources=out.get("sources") or {},
        output_contracts=out.get("contracts") or {},
        settings=g.settings,
        notes=["Compiled locally by HookLens from the scanned project."],
    )
    index = AstIndex(bundle)
    if index.main is None:
        raise AnalysisError(f"{c.name}: contract definition not found in the compiled AST.")
    dep = ((bundle.contract_output().get("evm") or {}).get("deployedBytecode") or {}).get("object") or ""
    code = hex_to_bytes("0x" + dep.removeprefix("0x")) if dep else b""
    declared = declared_permissions(SimpleNamespace(index=index))  # type: ignore[arg-type]
    if declared:
        perms, perm_source = from_flags(declared), "declared"
    else:
        perms, perm_source = from_flags({cb: True for cb in c.callbacks}), "implemented-callbacks"
    resolved = _LocalResolved(
        source=_LocalSource(bundle=bundle, contract_name=c.name, compiler_version=g.version, notes=bundle.notes),
        logic_code=code,
        runtime_code_hash=keccak_hex(code) if code else None,
    )
    ctx = AnalysisContext(
        chain_id=0,
        address=f"source:{c.file}:{c.name}",
        block_number=0,
        pool_manager=None,
        permissions=perms,
        logic_facts=analyze_bytecode(code),
        proxy_facts=None,
        resolved=resolved,
        index=index,
        proxy_index=None,
        mode="source",
        permission_source=perm_source,
    )
    res = run_analyzers(ctx, analyzers=analyzers)
    s = summarize(perms)
    extra = {
        "permissions": {
            "source": perm_source,
            "enabled_flags": s["enabled_flags"],
            "callbacks": s["callbacks"],
            "affected_operations": s["affected_operations"],
            "return_delta_flags": s["return_delta_flags"],
            "can_affect_withdrawals": s["can_affect_withdrawals"],
        },
        "solc_version": g.version,
        "bytecode": "compiled"
        if code
        else ("unavailable: " + "; ".join(g.codegen_errors[:1]) if g.codegen == "failed" else "unavailable"),
    }
    if not code:
        res.runs.append(
            {
                "analyzer_id": "bytecode",
                "status": "skipped",
                "reason": "runtime bytecode unavailable; selector and opcode checks were not performed",
                "duration_ms": 0,
                "findings": 0,
            }
        )
    return res, extra


def _finding_record(
    f: FindingItem, out: Collector, c: ContractInfo, project: Project, project_files: list[str]
) -> dict[str, Any]:
    code = f.finding_id.split("-")[1]
    info = rule_info(code, f.rule_id)
    evidence = []
    locations = []
    for eid in f.evidence_ids:
        ev = out.evidence.get(eid)
        if ev is None:
            continue
        excerpt = (ev.data.get("excerpt") or {}) if isinstance(ev.data.get("excerpt"), dict) else {}
        loc = None
        if ev.source_file and ev.line_start:
            loc = {
                "file": project.repo_path(ev.source_file) or ev.source_file,
                "unit": ev.source_file,
                "in_project": ev.source_file in project_files,
                "start_line": ev.line_start,
                "end_line": ev.line_end or ev.line_start,
                "function": ev.function_name,
            }
            locations.append(loc)
        evidence.append(
            {
                "id": ev.evidence_id,
                "kind": ev.kind,
                "title": ev.title,
                "basis": ev.basis.value,
                "location": loc,
                "excerpt": excerpt.get("code"),
                "excerpt_start_line": excerpt.get("line_start"),
                "data": _evidence_data(ev.kind, ev.data),
            }
        )
    # Prefer code in the hook's own file (e.g. its _beforeSwap override) over a shared base contract.
    primary = next(
        (loc for loc in locations if loc["unit"] == c.file),
        next((loc for loc in locations if loc["in_project"]), locations[0] if locations else None),
    )
    return {
        "id": f.finding_id,
        "rule": rule_key(code, f.rule_id),
        "rule_id": f.rule_id,
        "rule_name": info.name,
        "analyzer": f.analyzer_id,
        "category": f.category,
        "contract": c.name,
        "contract_file": project.repo_path(c.file) or c.file,
        "title": f.title,
        "severity": f.severity.value,
        "severity_rationale": f.severity_rationale,
        "confidence_basis": f.confidence_basis.value,
        "status": f.status.value,
        "description": f.description,
        "affected_functions": f.affected_functions,
        "lp_implications": f.lp_implications,
        "remediation": f.remediation,
        "limitations": f.limitations,
        "related_scenarios": f.related_scenarios,
        "location": primary,
        "locations": locations,
        "evidence": evidence,
        "fingerprint": f.finding_id,
    }


_EV_KEEP = {
    "permission_bits": ("derivation", "enabled_flags", "callbacks"),
    "state_variable": ("name", "type", "visibility", "constant", "immutable"),
    "bytecode_fact": ("selectors", "expected_missing", "opcode_counts"),
}


def _evidence_data(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    keep = _EV_KEEP.get(kind)
    src = {k: v for k, v in data.items() if k != "excerpt"}
    if keep is not None:
        src = {k: v for k, v in src.items() if k in keep}
    out: dict[str, Any] = {}
    for k, v in src.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v if not isinstance(v, str) else v[:500]
        elif (
            isinstance(v, list)
            and len(v) <= 64
            and all(isinstance(x, (str, int, float, bool)) for x in v)
            or isinstance(v, dict)
            and len(v) <= 64
            and all(isinstance(x, (str, int, float, bool)) for x in v.values())
        ):
            out[k] = v
    return out


def fails(report: dict[str, Any], fail_on: str) -> bool:
    if fail_on == "never":
        return False
    limit = SEVERITY_RANK[fail_on]
    return any(SEVERITY_RANK[f["severity"]] <= limit for f in report.get("_all_findings", report["findings"]))


def public(report: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if not k.startswith("_")}


__all__ = ["SEVERITY_ORDER", "Severity", "SourceInfo", "fails", "public", "run_scan"]
