"""Compile a local project with solc (standard JSON) to obtain ASTs, ABIs and storage layouts.

* Every source is passed to solc in memory; solc runs in an empty temporary directory and is never
  allowed to read the scanned project, so the compiler sees exactly the files HookLens resolved.
* Compilation runs in two phases: analysis only (AST, ABI, storage layout, selectors) for every
  file, then code generation only for the contracts being analysed. A code-generation failure
  (e.g. "stack too deep") is recorded and bytecode-derived checks are skipped; it never hides the
  AST-based analysis.
* solc binaries come from py-solc-x (binaries.soliditylang.org); downloads can be disabled.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hooklens.errors import AnalysisError
from hooklens.local import semver
from hooklens.local.project import Project, SourceTree, closure

PHASE1_OUTPUT = ["abi", "storageLayout", "evm.methodIdentifiers", "metadata"]
PHASE2_OUTPUT = ["evm.deployedBytecode.object", "evm.deployedBytecode.immutableReferences"]


@dataclass
class CompileGroup:
    version: str
    targets: list[str]
    evm_version: str | None
    status: str = "pending"  # compiled | failed
    output: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: int = 0
    codegen: str = "not-run"  # ok | failed | not-run
    codegen_errors: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "solc_version": self.version,
            "evm_version": self.evm_version,
            "targets": self.targets,
            "status": self.status,
            "errors": self.errors,
            "warning_count": self.warnings,
            "bytecode": self.codegen,
            "bytecode_errors": self.codegen_errors,
        }


class Solc:
    def __init__(self, allow_download: bool) -> None:
        self.allow_download = allow_download
        try:
            import solcx
        except ImportError as e:  # pragma: no cover - dependency of the package
            raise AnalysisError("py-solc-x is not installed.") from e
        self._solcx = solcx
        self._installable: list[semver.Version] | None = None

    def installed(self) -> list[semver.Version]:
        try:
            return sorted(semver.parse_version(str(v)) for v in self._solcx.get_installed_solc_versions())
        except Exception:
            return []

    def candidates(self) -> list[semver.Version]:
        vs = set(self.installed())
        if self.allow_download:
            if self._installable is None:
                try:
                    self._installable = [
                        semver.parse_version(str(v)) for v in self._solcx.get_installable_solc_versions()
                    ]
                except Exception:
                    self._installable = []
            vs |= set(self._installable)
        return sorted(vs)

    def executable(self, version: str) -> Path:
        v = semver.parse_version(version)
        if v not in self.installed():
            if not self.allow_download:
                raise AnalysisError(
                    f"solc {version} is not installed and compiler downloads are disabled.",
                    hint=f"Install it with: python -c \"import solcx; solcx.install_solc('{version}')\" "
                    "or allow downloads (remove --offline / set compiler.allow_download = true).",
                )
            try:
                self._solcx.install_solc(version)
            except Exception as e:
                raise AnalysisError(
                    f"solc {version} could not be downloaded: {type(e).__name__}.",
                    hint="Check network access to binaries.soliditylang.org, or install solc with py-solc-x.",
                ) from e
        return Path(str(self._solcx.install.get_executable(version)))


def choose_versions(project: Project, tree: SourceTree, targets: list[str], solc: Solc) -> dict[str, list[str]]:
    """Group target files by the solc version that will compile them."""
    if project.solc:
        return {project.solc: list(targets)}
    cands = solc.candidates()
    if not cands:
        raise AnalysisError(
            "No solc compiler is installed and the list of downloadable versions is unavailable.",
            hint="Install a compiler (python -m solcx.install 0.8.26) or set compiler.solc and allow downloads.",
        )
    groups: dict[str, list[str]] = {}
    unsatisfiable: list[str] = []
    for t in targets:
        exprs = [e for u in sorted(closure(tree, t)) if u in tree.sources for e in semver.pragmas(tree.sources[u])]
        try:
            best = semver.best_version(cands, exprs)
        except ValueError:
            best = None
        if best is None:
            unsatisfiable.append(t)
            continue
        groups.setdefault(semver.fmt(best), []).append(t)
    if unsatisfiable and not groups:
        raise AnalysisError(
            "No available solc version satisfies the version pragmas of: " + ", ".join(unsatisfiable[:5]),
            hint="Pin a version with --solc 0.8.x or compiler.solc in hooklens.toml.",
        )
    for t in unsatisfiable:  # compile with the highest group version so solc reports the real error
        groups.setdefault(max(groups, key=semver.parse_version), []).append(t)
    return groups


def _default_evm(version: str, configured: str | None) -> str | None:
    if configured:
        return configured
    # Uniswap v4 code uses transient storage (EIP-1153): require at least cancun when solc supports it.
    return "cancun" if semver.parse_version(version) >= (0, 8, 24) else None


def _run(exe: Path, std: dict[str, Any], timeout: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hooklens-solc-") as cwd:
        try:
            proc = subprocess.run(
                [str(exe), "--standard-json"],
                input=json.dumps(std),
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=cwd,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise AnalysisError(f"solc did not finish within {timeout}s.", hint="Raise compiler.timeout_s.") from e
        except OSError as e:
            raise AnalysisError(f"solc could not be started: {e.strerror}.") from e
    try:
        out: dict[str, Any] = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AnalysisError("solc returned output that is not JSON: " + (proc.stderr or proc.stdout)[:300]) from e
    return out


def compile_group(
    project: Project,
    tree: SourceTree,
    group: CompileGroup,
    solc: Solc,
    timeout: int,
) -> None:
    exe = solc.executable(group.version)
    units = sorted(set().union(*(closure(tree, t) for t in group.targets)) & set(tree.sources))
    settings: dict[str, Any] = {
        "remappings": [r.solc() for r in project.remappings],
        "optimizer": {"enabled": project.optimizer, "runs": project.optimizer_runs},
        "outputSelection": {"*": {"*": PHASE1_OUTPUT, "": ["ast"]}},
    }
    if group.evm_version:
        settings["evmVersion"] = group.evm_version
    std = {"language": "Solidity", "sources": {u: {"content": tree.sources[u]} for u in units}, "settings": settings}
    out = _run(exe, std, timeout)
    errs = [e for e in out.get("errors") or [] if e.get("severity") == "error"]
    group.warnings = sum(1 for e in out.get("errors") or [] if e.get("severity") == "warning")
    group.settings = {k: v for k, v in settings.items() if k != "outputSelection"}
    if errs:
        group.status = "failed"
        group.errors = [_err(e) for e in errs[:25]]
        return
    group.status = "compiled"
    group.output = out


def generate_bytecode(
    project: Project, tree: SourceTree, group: CompileGroup, solc: Solc, contracts: list[tuple[str, str]], timeout: int
) -> None:
    """Phase 2: runtime bytecode for the analysed contracts only."""
    if not contracts:
        return
    exe = solc.executable(group.version)
    wanted = {u for u, _ in contracts}
    units = sorted(set().union(*(closure(tree, u) for u in wanted)) & set(tree.sources))
    sel: dict[str, dict[str, list[str]]] = {}
    for u, name in contracts:
        sel.setdefault(u, {})[name] = PHASE2_OUTPUT
    settings: dict[str, Any] = {
        "remappings": [r.solc() for r in project.remappings],
        "optimizer": {"enabled": project.optimizer, "runs": project.optimizer_runs},
        "outputSelection": sel,
    }
    if project.via_ir:
        settings["viaIR"] = True
    if group.evm_version:
        settings["evmVersion"] = group.evm_version
    std = {"language": "Solidity", "sources": {u: {"content": tree.sources[u]} for u in units}, "settings": settings}
    try:
        out = _run(exe, std, timeout)
    except AnalysisError as e:
        group.codegen, group.codegen_errors = "failed", [e.message]
        return
    errs = [e for e in out.get("errors") or [] if e.get("severity") == "error"]
    if errs:
        group.codegen = "failed"
        group.codegen_errors = [_err(e)["message"] for e in errs[:5]]
        return
    group.codegen = "ok"
    contracts_out = group.output.setdefault("contracts", {})
    for u, by_name in (out.get("contracts") or {}).items():
        for name, data in by_name.items():
            contracts_out.setdefault(u, {}).setdefault(name, {}).setdefault("evm", {}).update(data.get("evm") or {})


def _err(e: dict[str, Any]) -> dict[str, Any]:
    loc = e.get("sourceLocation") or {}
    return {
        "type": e.get("type"),
        "message": (e.get("message") or "")[:500],
        "file": loc.get("file"),
        "formatted": (e.get("formattedMessage") or "")[:1500],
    }
