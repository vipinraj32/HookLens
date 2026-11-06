"""Markdown summary for GitHub job summaries and pull-request comments."""

from __future__ import annotations

from typing import Any

from hooklens.scanner import SEVERITY_RANK

COMMENT_MARKER = "<!-- hooklens-report -->"
_ICON = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "🟦", "informational": "⬜", "unknown": "🟪"}
_STATUS = {
    "completed": "✅ completed",
    "partial": "⚠️ partial (some files were not analysed)",
    "failed": "❌ failed",
    "no-hooks": "ℹ️ no Uniswap v4 hooks identified",
}


def _md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def render(
    report: dict[str, Any],
    *,
    artifacts: dict[str, str] | None = None,
    max_findings: int = 10,
    fail_on: str | None = None,
    compact: bool = False,
) -> str:
    s = report["summary"]
    scan = report["scan"]
    src = scan["source"]
    name = src.get("display_name") or src.get("target")
    lines = [COMMENT_MARKER, f"## HookLens static scan: {_md(name)}", ""]
    commit = f" at `{src['commit'][:12]}`" if src.get("commit") else ""
    lines.append(
        f"**Status:** {_STATUS.get(scan['status'], scan['status'])}{commit} · HookLens {report['tool']['version']}"
    )
    for p in scan.get("problems") or []:
        lines.append(f"> ⚠️ {_md(p)}")
    lines += [
        "",
        "| Contracts analysed | Hooks | Candidates | Findings |",
        "|---:|---:|---:|---:|",
        f"| {s['contracts_analyzed']} | {s['hooks']} | {s['candidates']} | {s['findings_total']} |",
        "",
        "| Severity | Count |",
        "|---|---:|",
    ]
    for sev in ("critical", "high", "medium", "low", "informational", "unknown"):
        n = s["by_severity"].get(sev, 0)
        if n or sev in ("critical", "high", "medium", "low"):
            lines.append(f"| {_ICON[sev]} {sev} | {n} |")
    fail_on = fail_on or scan["configuration"].get("fail_on")
    if fail_on and fail_on != "never":
        breached = any(SEVERITY_RANK[f["severity"]] <= SEVERITY_RANK[fail_on] for f in report["findings"])
        lines += ["", f"**Gate (`--fail-on {fail_on}`):** " + ("❌ threshold reached" if breached else "✅ passed")]
    top = sorted(
        (f for f in report["findings"] if f["severity"] != "informational"),
        key=lambda f: (SEVERITY_RANK[f["severity"]], f["contract"], f["rule"]),
    )[:max_findings]
    if top:
        lines += [
            "",
            "### Highest-severity findings",
            "",
            "| Severity | Contract | Finding | Location |",
            "|---|---|---|---|",
        ]
        for f in top:
            loc = f.get("location")
            where = f"`{_md(loc['file'])}:{loc['start_line']}`" if loc else "no source location"
            lines.append(
                f"| {_ICON[f['severity']]} {f['severity']} | {_md(f['contract'])} | {_md(f['title'])} (`{f['rule']}`) | {where} |"
            )
        rest = len([f for f in report["findings"] if f["severity"] != "informational"]) - len(top)
        if rest > 0:
            lines.append(f"\n…and {rest} more in the full report.")
    elif s["contracts_analyzed"]:
        lines += ["", "No findings above informational. This does not mean the hook is safe."]
    if not compact:
        analysed = [c for c in report["contracts"] if c["analyzed"]]
        if analysed:
            lines += [
                "",
                "<details><summary>Contracts analysed</summary>",
                "",
                "| Contract | Kind | File | Callbacks |",
                "|---|---|---|---|",
            ]
            for c in analysed:
                cbs = ", ".join((c.get("permissions") or {}).get("callbacks") or []) or "—"
                lines.append(
                    f"| {_md(c['name'])} | {c['kind']} ({c.get('confidence') or '-'}) | `{_md(c.get('repo_path') or c['file'])}` | {_md(cbs)} |"
                )
            lines += ["", "</details>"]
    if artifacts:
        lines += ["", "**Reports:** " + " · ".join(f"{k}: `{_md(v)}`" for k, v in artifacts.items())]
    lines += [
        "",
        "<sub>Static source analysis: findings are code patterns to investigate, not confirmed exploits, and no "
        "execution was performed. Absence of findings does not mean a hook is safe.</sub>",
        "",
    ]
    return "\n".join(lines)
