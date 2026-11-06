"""`hooklens` command-line interface."""

from __future__ import annotations

import contextlib
import json
import os
import platform
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import click

from hooklens import __version__
from hooklens.config import (
    ANALYZER_IDS,
    CONFIG_NAME,
    FAIL_ON_CHOICES,
    SEVERITIES,
    ScanConfig,
    find_config,
    load_config,
    render_default,
    validate,
)
from hooklens.errors import EXIT_CONFIG, EXIT_FINDINGS, EXIT_OK, ConfigError, HookLensError, SourceError

SEV_COLOR = {
    "critical": "red",
    "high": "bright_red",
    "medium": "yellow",
    "low": "blue",
    "informational": "white",
    "unknown": "magenta",
}


class Console:
    def __init__(self, quiet: bool, verbose: bool) -> None:
        self.quiet, self.verbose = quiet, verbose

    def step(self, stage: str, msg: str) -> None:
        if not self.quiet:
            click.echo(click.style(f"[{stage}]", fg="cyan") + f" {msg}", err=True)

    def info(self, msg: str = "") -> None:
        if not self.quiet:
            click.echo(msg)

    def error(self, err: HookLensError) -> None:
        click.echo(click.style("error: ", fg="red", bold=True) + err.message, err=True)
        if err.hint:
            click.echo(click.style("hint: ", fg="yellow") + err.hint, err=True)


def _setup_streams() -> None:
    for s in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            if s.isatty():
                s.reconfigure(errors="replace")  # type: ignore[union-attr]
            else:  # files, pipes, $GITHUB_STEP_SUMMARY: always UTF-8, whatever the locale
                s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="hooklens", message="%(prog)s %(version)s")
def main() -> None:
    """HookLens: static scanner for Uniswap v4 hooks.

    \b
    Quick start:
      hooklens scan ./contracts --local --html report.html
      hooklens scan https://github.com/owner/v4-hook-repo --html report.html
      hooklens scan . --json report.json --sarif report.sarif --fail-on high

    Exit codes: 0 ok, 1 findings at/above --fail-on, 2 usage/config error, 3 source error,
    4 analysis error, 5 report error.
    """
    _setup_streams()


# ====================================================================== scan


def _sev_choice() -> click.Choice:
    return click.Choice(SEVERITIES, case_sensitive=False)


@main.command()
@click.argument("target", default=".", metavar="TARGET")
@click.option("--local", "force_local", is_flag=True, help="Treat TARGET as a local path (never fetch anything).")
@click.option("--ref", help="Branch, tag or commit to scan (GitHub targets).")
@click.option("--html", "html_out", type=click.Path(dir_okay=False), help="Write a standalone HTML report.")
@click.option("--json", "json_out", type=click.Path(dir_okay=False), help="Write the JSON report (schema v1).")
@click.option("--sarif", "sarif_out", type=click.Path(dir_okay=False), help="Write a SARIF 2.1.0 report.")
@click.option("--contract", "contracts", multiple=True, help="Only analyse this contract (repeatable).")
@click.option("--path", "paths", multiple=True, help="Source path relative to the project root (repeatable).")
@click.option("--exclude", multiple=True, help="Glob of files to skip, e.g. 'src/legacy/**' (repeatable).")
@click.option("--no-default-excludes", is_flag=True, help="Do not skip test/, script/, lib/, mocks/, *.t.sol ...")
@click.option("--include-mocks", is_flag=True, help="Also analyse contracts classified as mocks.")
@click.option("--remapping", "remappings", multiple=True, help="Import remapping prefix=path (repeatable).")
@click.option("--solc", "solc_version", help="Exact solc version to use, e.g. 0.8.26.")
@click.option("--evm-version", help="EVM version passed to solc (default: foundry.toml, else cancun).")
@click.option("--offline", is_flag=True, help="Never download a solc compiler.")
@click.option(
    "--analyzer", "analyzers", multiple=True, type=click.Choice(ANALYZER_IDS), help="Run only these analyzers."
)
@click.option(
    "--disable-analyzer", "disabled", multiple=True, type=click.Choice(ANALYZER_IDS), help="Skip an analyzer."
)
@click.option("--severity-threshold", type=_sev_choice(), help="Lowest severity included in reports [informational].")
@click.option("--sarif-min-severity", type=_sev_choice(), help="Lowest severity emitted to SARIF [low].")
@click.option(
    "--fail-on",
    type=click.Choice(FAIL_ON_CHOICES, case_sensitive=False),
    help="Exit 1 when a finding at or above this severity exists [never].",
)
@click.option("--config", "config_path", type=click.Path(dir_okay=False, exists=True), help=f"Path to {CONFIG_NAME}.")
@click.option("--no-config", is_flag=True, help=f"Ignore {CONFIG_NAME} files.")
@click.option("--timeout", default=300, show_default=True, help="Seconds allowed for repository download / clone.")
@click.option("--no-submodules", is_flag=True, help="Do not fetch git submodules of a GitHub repository.")
@click.option("--summary-md", type=click.Path(dir_okay=False), help="Also write a Markdown summary (CI job summaries).")
@click.option("-q", "--quiet", is_flag=True, help="Only print errors and the final status line.")
@click.option("-v", "--verbose", is_flag=True, help="List every finding, including informational ones.")
def scan(target: str, force_local: bool, ref: str | None, html_out: str | None, json_out: str | None, sarif_out: str | None,
         contracts: tuple[str, ...], paths: tuple[str, ...], exclude: tuple[str, ...], no_default_excludes: bool,
         include_mocks: bool, remappings: tuple[str, ...], solc_version: str | None, evm_version: str | None,
         offline: bool, analyzers: tuple[str, ...], disabled: tuple[str, ...], severity_threshold: str | None,
         sarif_min_severity: str | None, fail_on: str | None, config_path: str | None, no_config: bool, timeout: int,
         no_submodules: bool, summary_md: str | None, quiet: bool, verbose: bool) -> None:  # fmt: skip
    """Scan a local Solidity project or a GitHub repository for Uniswap v4 hook risks.

    TARGET is a directory, a .sol file, or https://github.com/<owner>/<repo>[/tree/<ref>/<path>].
    """
    from hooklens import remote
    from hooklens.scanner import SourceInfo

    con = Console(quiet, verbose)
    overrides: dict[str, Any] = {
        "contracts": list(contracts) or None,
        "paths": list(paths) or None,
        "exclude": list(exclude) or None,
        "default_excludes": False if no_default_excludes else None,
        "include_mocks": True if include_mocks else None,
        "remappings": [r.replace("\\", "/") for r in remappings] or None,
        "solc": solc_version,
        "evm_version": evm_version,
        "allow_solc_download": False if offline else None,
        "analyzers": list(analyzers) or None,
        "disable_analyzers": list(disabled) or None,
        "severity_threshold": severity_threshold.lower() if severity_threshold else None,
        "sarif_min_severity": sarif_min_severity.lower() if sarif_min_severity else None,
        "fail_on": fail_on.lower() if fail_on else None,
        "html": html_out,
        "json": json_out,
        "sarif": sarif_out,
    }
    remote_target = remote.is_remote(target) and not force_local
    code = EXIT_OK
    cfg: ScanConfig | None = None
    report: dict[str, Any] | None = None
    try:
        if force_local and remote.is_remote(target):
            raise ConfigError("--local was given but TARGET is a URL.")
        if remote_target:
            con.step("source", f"Fetching {target}" + (f" @ {ref}" if ref else ""))
            with remote.acquire(target, ref=ref, timeout=timeout, submodules=not no_submodules) as ws:
                rr = ws.repo
                src = SourceInfo(
                    kind="github",
                    target=target,
                    url=rr.url,
                    ref=rr.ref,
                    commit=ws.commit,
                    branch=ws.branch,
                    subpath=rr.subpath,
                    display_name=rr.name + (f"/{rr.subpath}" if rr.subpath else ""),
                    notes=ws.notes,
                )
                for n in ws.notes:
                    con.step("source", n)
                con.step("source", f"Checked out {rr.name} at {(ws.commit or 'unknown commit')[:12]}")
                cfg = _resolve_config(
                    ws.scan_target, overrides, config_path, no_config, trusted=False, boundary=ws.root, con=con
                )
                report = _scan(ws.scan_target, cfg, src, ws.root, con)
        else:
            path = Path(target)
            if not path.exists():
                raise SourceError(f"Path does not exist: {target}")
            cfg = _resolve_config(path, overrides, config_path, no_config, trusted=True, boundary=None, con=con)
            from hooklens.local.project import find_repo_root

            repo_root = find_repo_root(path.resolve())
            commit, branch = remote.read_git_head(repo_root) if repo_root else (None, None)
            src = SourceInfo(
                kind="local",
                target=target,
                commit=commit,
                branch=branch,
                display_name=(repo_root.name + "/" + path.resolve().relative_to(repo_root).as_posix()).rstrip("/.")
                if repo_root and path.resolve() != repo_root
                else path.resolve().name,
            )
            report = _scan(path, cfg, src, None, con)
        _write_reports(report, cfg, summary_md, con)
        code = _final(report, cfg, con)
    except HookLensError as err:
        con.error(err)
        code = err.exit_code
        if cfg is not None and cfg.json and report is None:
            _write_failure(cfg.json, target, err, con)
    except KeyboardInterrupt:
        click.echo("\ninterrupted; temporary files were removed.", err=True)
        code = 130
    sys.exit(code)


def _resolve_config(
    target: Path, overrides: dict[str, Any], config_path: str | None, no_config: bool, *, trusted: bool,
    boundary: Path | None, con: Console,
) -> ScanConfig:  # fmt: skip
    from hooklens.local.project import discover_project

    cfg_file: Path | None = None
    if config_path:
        cfg_file = Path(config_path)
    elif not no_config:
        root = discover_project(target, ScanConfig(), boundary=boundary).root
        cfg_file = find_config(root)
    # An explicitly passed --config is the user's own file even when scanning a remote repository.
    cfg = load_config(cfg_file, trusted=trusted or bool(config_path))
    if cfg_file:
        con.step("config", f"Using {cfg_file}")
    if cfg.ignored_keys:
        con.step(
            "config", "Ignored report/CI settings from the scanned repository's config: " + ", ".join(cfg.ignored_keys)
        )
    cfg = replace(cfg, **{k: v for k, v in overrides.items() if v is not None})
    validate(cfg)
    return cfg


def _scan(target: Path, cfg: ScanConfig, src: Any, boundary: Path | None, con: Console) -> dict[str, Any]:
    from hooklens.scanner import run_scan

    return run_scan(target, cfg, src, boundary=boundary, progress=con.step)


def _write_reports(report: dict[str, Any], cfg: ScanConfig, summary_md: str | None, con: Console) -> None:
    from hooklens.reports import dumps, write_text
    from hooklens.scanner import public

    doc = public(report)
    written: dict[str, str] = {}
    if cfg.json:
        written["JSON"] = str(write_text(cfg.json, dumps(doc)))
    if cfg.sarif:
        from hooklens.reports import sarif

        written["SARIF"] = str(write_text(cfg.sarif, json.dumps(sarif.render(doc), indent=2) + "\n"))
    if cfg.html:
        from hooklens.reports import html

        written["HTML"] = str(write_text(cfg.html, html.render(doc)))
    if summary_md:
        from hooklens.reports import markdown

        names = {k: Path(v).name for k, v in written.items()}
        written["Summary"] = str(write_text(summary_md, markdown.render(doc, artifacts=names, fail_on=cfg.fail_on)))
    report["_written"] = written


def _write_failure(path: str, target: str, err: HookLensError, con: Console) -> None:
    """A machine-readable record of a failed scan, so CI can tell 'scan broke' from 'no findings'."""
    from hooklens.reports import dumps, write_text
    from hooklens.scanner import LIMITATIONS, SCHEMA_ID, SCHEMA_VERSION, SCOPE_STATEMENT, _now

    doc: dict[str, Any] = {
        "$schema": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "hooklens", "version": __version__, "analyzer_version": "n/a"},
        "scan": {
            "id": "failed",
            "kind": "static-source",
            "status": "failed",
            "problems": [err.message],
            "error": err.to_dict(),
            "started_at": _now(),
            "finished_at": _now(),
            "source": {"kind": "github" if target.startswith("https://") else "local", "target": target},
            "configuration": {},
        },
        "files": {"selected": [], "excluded": [], "unresolved_imports": [], "blocked_by_imports": []},
        "compilation": [],
        "contracts": [],
        "findings": [],
        "execution_results": None,
        "summary": {
            "contracts_discovered": 0,
            "contracts_analyzed": 0,
            "findings_total": 0,
            "by_severity": {s: 0 for s in (*SEVERITIES, "unknown")},
            "highest_severity": None,
        },
        "scope": SCOPE_STATEMENT,
        "limitations": LIMITATIONS,
    }
    try:
        write_text(path, dumps(doc))
        con.step("report", f"Wrote failure record to {path}")
    except HookLensError:
        pass


def _final(report: dict[str, Any], cfg: ScanConfig, con: Console) -> int:
    from hooklens.scanner import SEVERITY_RANK, fails

    s = report["summary"]
    status = report["scan"]["status"]
    con.info("")
    con.info(click.style("HookLens static scan", bold=True) + f"  ({report['scan']['source'].get('display_name')})")
    for c in report["contracts"]:
        if c["analyzed"]:
            cbs = ", ".join((c.get("permissions") or {}).get("callbacks") or []) or "none"
            con.info(f"  {c['kind']:<9} {c['name']}  {c.get('repo_path') or c['file']}:{c['line']}  callbacks: {cbs}")
    if con.verbose:
        for c in report["contracts"]:
            if not c["analyzed"]:
                con.info(click.style(f"  skipped   {c['name']} ({c['skip_reason']})", dim=True))
    all_f = report.get("_all_findings", report["findings"])
    shown = [f for f in all_f if con.verbose or f["severity"] != "informational"]
    if shown:
        con.info("")
    for f in sorted(shown, key=lambda f: (SEVERITY_RANK[f["severity"]], f["contract"], f["rule"])):
        loc = f.get("location")
        where = f"{loc['file']}:{loc['start_line']}" if loc else "no source location"
        con.info(
            "  "
            + click.style(f"{f['severity'].upper():<14}", fg=SEV_COLOR[f["severity"]], bold=True)
            + f"{f['title']}  [{f['rule']}]\n                 {f['contract']} - {where}"
        )
    counts = ", ".join(f"{k} {v}" for k, v in s["by_severity"].items() if v) or "none"
    con.info("")
    con.info(f"Contracts analysed: {s['contracts_analyzed']}  (discovered {s['contracts_discovered']}: "
             f"{s['hooks']} hook(s), {s['candidates']} candidate(s))")  # fmt: skip
    con.info(f"Findings: {s['findings_total']}  ({counts})")
    hidden = sum(1 for f in all_f if f["severity"] == "informational")
    if hidden and not con.verbose:
        con.info(click.style(f"  {hidden} informational finding(s) not listed; use -v or open a report.", dim=True))
    for kind, path in (report.get("_written") or {}).items():
        con.info(f"{kind} report: {path}")
    for p in report["scan"].get("problems") or []:
        click.echo(click.style("warning: ", fg="yellow") + p, err=True)
    if status == "no-hooks":
        click.echo(
            click.style("note: ", fg="yellow")
            + "no Uniswap v4 hook contracts were identified, so no hook analysis ran. Use --contract NAME to "
            "analyse a specific contract, or -v to see how each contract was classified.",
            err=True,
        )
    if status in ("failed", "partial"):
        click.echo(
            click.style(f"Scan {status}: not every requested contract was analysed (exit 4).", fg="red"), err=True
        )
        return 4
    if fails(report, cfg.fail_on):
        click.echo(click.style(f"Gate: findings at or above '{cfg.fail_on}' present (exit 1).", fg="red"), err=True)
        return EXIT_FINDINGS
    if cfg.fail_on != "never":
        click.echo(click.style(f"Gate: no findings at or above '{cfg.fail_on}'.", fg="green"), err=True)
    click.echo(f"Scan {status}.", err=True)
    return EXIT_OK


# ====================================================================== init


@main.command()
@click.argument("directory", default=".", type=click.Path(file_okay=False, exists=True))
@click.option("--github-action", is_flag=True, help="Also write .github/workflows/hooklens.yml.")
@click.option("--fail-on", default="high", type=click.Choice(FAIL_ON_CHOICES, case_sensitive=False), show_default=True)
@click.option("--force", is_flag=True, help="Overwrite existing files.")
def init(directory: str, github_action: bool, fail_on: str, force: bool) -> None:
    """Create a starter hooklens.toml (and optionally a GitHub Actions workflow)."""
    from hooklens.local.project import discover_project

    root = Path(directory).resolve()
    try:
        proj = discover_project(root, ScanConfig())
        paths = [proj.rel(p) or "." for p in proj.scan_paths]
    except HookLensError:
        paths = ["src"]
    cfg_file = root / CONFIG_NAME
    created = []
    if cfg_file.exists() and not force:
        click.echo(f"{cfg_file} already exists (use --force to overwrite).", err=True)
        sys.exit(EXIT_CONFIG)
    cfg_file.write_text(render_default(paths, fail_on.lower()), encoding="utf-8")
    created.append(cfg_file)
    if github_action:
        wf = root / ".github" / "workflows" / "hooklens.yml"
        if wf.exists() and not force:
            click.echo(f"{wf} already exists (use --force to overwrite).", err=True)
            sys.exit(EXIT_CONFIG)
        wf.parent.mkdir(parents=True, exist_ok=True)
        wf.write_text(workflow_template([p for p in paths if p != "."], fail_on.lower()), encoding="utf-8")
        created.append(wf)
    for p in created:
        click.echo(f"created {p}")
    click.echo("Next: hooklens scan . --html hooklens-report.html")


def workflow_template(paths: str | list[str], fail_on: str) -> str:
    paths = " ".join(paths) if isinstance(paths, list) else paths
    paths = paths or '""'
    return f"""# HookLens static scan for Uniswap v4 hooks.
# Runs on pull requests and pushes; uploads SARIF to GitHub Code Scanning and the HTML/JSON reports as
# artifacts. No secrets, Anthropic key or HookLens server are needed for static scanning.
name: HookLens

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read
  security-events: write   # SARIF upload (skipped automatically for pull requests from forks)
  pull-requests: write     # only used when comment-on-pr is true

jobs:
  hooklens:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive   # Foundry dependencies (lib/) are usually git submodules
      # Pin to a release tag or commit SHA of HookLens once one is published.
      - uses: vipinraj32/HookLens@main
        with:
          paths: {paths}
          fail-on: {fail_on}
          html-out: hooklens-report.html
          json-out: hooklens-report.json
          sarif-out: hooklens.sarif
          comment-on-pr: false
"""


# ====================================================================== summary / rules / version


@main.command()
@click.argument("report_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--format", "fmt", type=click.Choice(["markdown", "text"]), default="markdown", show_default=True)
@click.option("--compact", is_flag=True, help="Shorter output (pull-request comments).")
@click.option("--artifact", "artifacts", multiple=True, help="name=filename listed under 'Reports' (repeatable).")
@click.option("--fail-on", type=click.Choice(FAIL_ON_CHOICES, case_sensitive=False))
def summary(report_json: str, fmt: str, compact: bool, artifacts: tuple[str, ...], fail_on: str | None) -> None:
    """Render a summary of a JSON report (used for CI job summaries and PR comments)."""
    from hooklens.reports import markdown

    try:
        doc = json.loads(Path(report_json).read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or "summary" not in doc or "scan" not in doc:
            raise ValueError("not a HookLens report")
    except (OSError, ValueError) as e:
        click.echo(f"error: {report_json} is not a readable HookLens JSON report ({e}).", err=True)
        sys.exit(EXIT_CONFIG)
    arts = dict(a.split("=", 1) for a in artifacts if "=" in a)
    if doc["scan"].get("error") and not doc.get("contracts"):
        err = doc["scan"]["error"]
        click.echo(
            f"## HookLens static scan failed\n\n**{err.get('kind')}:** {err.get('message')}\n"
            + (f"\n{err.get('hint')}\n" if err.get("hint") else "")
        )
        return
    text = markdown.render(doc, artifacts=arts, compact=compact, fail_on=fail_on.lower() if fail_on else None)
    if fmt == "text":
        text = "\n".join(line for line in text.splitlines() if not line.startswith("<"))
    click.echo(text)


@main.command()
def rules() -> None:
    """List HookLens rule identifiers."""
    from hooklens.rules_catalog import _RULES

    for key, info in sorted(_RULES.items()):
        click.echo(f"HL.{key:<44} {info.short}")


@main.command()
def version() -> None:
    """Show HookLens, analyzer, Python and compiler versions."""
    from hooklens.analyzers.permissions_generated import V4_CORE_COMMIT
    from hooklens.analyzers.runner import ANALYZER_VERSION

    click.echo(f"hooklens {__version__}")
    click.echo(f"analyzers {ANALYZER_VERSION}")
    click.echo(f"v4-core permission table {V4_CORE_COMMIT[:12]}")
    click.echo(f"python {platform.python_version()} ({platform.system()})")
    try:
        import solcx

        vs = sorted(str(v) for v in solcx.get_installed_solc_versions())
        click.echo("solc installed: " + (", ".join(vs) if vs else "none (downloaded on first scan unless --offline)"))
    except Exception:
        click.echo("solc installed: unknown")


# ====================================================================== lab


@main.command()
@click.option("--hook", required=True, help="Deployed hook address.")
@click.option(
    "--chain", "chain_id", type=int, required=True, help="Chain id (1 mainnet, 11155111 Sepolia, 31337 local)."
)
@click.option("--pool-id", help="Pool to exercise (default: first discovered pool with liquidity).")
@click.option("--block", type=int, help="Fork block (default: the server pins head minus confirmations).")
@click.option(
    "--scenario", "scenarios", multiple=True, help="Scenario id to run (repeatable; default: all applicable)."
)
@click.option(
    "--api",
    default=lambda: os.environ.get("HOOKLENS_API", "http://127.0.0.1:8000"),
    show_default="$HOOKLENS_API or http://127.0.0.1:8000",
)
@click.option("--json", "json_out", type=click.Path(dir_okay=False), help="Write execution results as JSON.")
@click.option("--timeout", default=1800, show_default=True, help="Seconds to wait for the simulation.")
@click.option("--fail-on-failed", is_flag=True, help="Exit 1 if any scenario run failed or reverted unexpectedly.")
@click.option("-q", "--quiet", is_flag=True)
def lab(hook: str, chain_id: int, pool_id: str | None, block: int | None, scenarios: tuple[str, ...], api: str,
        json_out: str | None, timeout: int, fail_on_failed: bool, quiet: bool) -> None:  # fmt: skip
    """Execution testing: fork the chain and run HookLens scenarios against a deployed hook.

    Requires a running HookLens server (API + simulation worker with Foundry and an RPC endpoint).
    Results are execution-tested observations on one fork and are reported separately from static findings.
    """
    from hooklens.lab import lab_exit_code, run_lab
    from hooklens.reports import dumps, write_text

    con = Console(quiet, False)
    try:
        res = run_lab(
            api=api,
            chain_id=chain_id,
            hook=hook,
            pool_id=pool_id,
            block=block,
            scenarios=list(scenarios) or None,
            timeout_s=timeout,
            progress=lambda m: con.step("lab", m),
        )
    except HookLensError as err:
        con.error(err)
        sys.exit(err.exit_code)
    except KeyboardInterrupt:
        click.echo("\ninterrupted (the server-side simulation keeps running; cancel it from the web UI).", err=True)
        sys.exit(130)
    con.info("")
    con.info(click.style("HookLens execution testing (fork simulation)", bold=True))
    con.info(f"  hook {res['hook']} on chain {res['chain_id']}, fork block {res['fork_block']}, pool {res['pool_id']}")
    con.info(f"  simulation {res['simulation_id']}: {res['simulation_status']}")
    for r in res["runs"]:
        con.info(f"  - {r['scenario_id']:<24} {r['status']:<18} {r.get('status_reason') or ''}")
        for st in r["steps"][:20]:
            rv = f"  revert: {st['revert']}" if st.get("revert") else ""
            con.info(f"      {str(st.get('status') or ''):<16} {st['name']}{rv}")
        if r.get("repro_command"):
            con.info(click.style(f"      reproduce: {r['repro_command']}", dim=True))
    if json_out:
        try:
            write_text(json_out, dumps(res))
            con.info(f"JSON results: {json_out}")
        except HookLensError as err:
            con.error(err)
            sys.exit(err.exit_code)
    sys.exit(lab_exit_code(res, fail_on_failed))


if __name__ == "__main__":  # pragma: no cover
    main()
