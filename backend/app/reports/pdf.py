"""PDF rendering of a report document with reportlab (pure Python, works on every platform)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SEV_COLORS = {
    "critical": "#b91c1c",
    "high": "#dc2626",
    "medium": "#d97706",
    "low": "#2563eb",
    "informational": "#6b7280",
    "unknown": "#6b7280",
}
STATUS_COLORS = {
    "passed": "#15803d",
    "failed": "#b91c1c",
    "unexpected_revert": "#dc2626",
    "partial": "#d97706",
    "unsupported": "#6b7280",
    "infra_error": "#7c3aed",
    "inconclusive": "#6b7280",
}


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "—")), style)


def render_pdf(c: dict[str, Any], content_hash: str, path: Path) -> None:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#374151"))
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=ss["Heading3"], fontSize=9.5, spaceBefore=6, spaceAfter=2)
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=7, leading=8.5)
    grid = TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ]
    )

    def kv_table(rows: list[tuple[str, Any]]) -> Table:
        t = Table([[_p(k, small), _p(v, mono)] for k, v in rows], colWidths=[40 * mm, 135 * mm])
        t.setStyle(
            TableStyle(
                [("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
            )
        )
        return t

    story: list[Any] = []
    ident = c["identity"]
    story += [
        _p("HookLens report", h1),
        _p(f"{ident.get('contract_name') or 'Hook'} · {ident['hook_address']} · chain {ident['chain_id']}", body),
        _p(f"Generated {c['generated_at']} by {c['generator']} · report v{c['report_version']}", small),
        _p(f"Content hash {content_hash}", small),
        Spacer(1, 4),
        _p(c["disclaimer"], small),
    ]

    story.append(_p("Identity & provenance", h2))
    story.append(
        kv_table(
            [
                ("Block", ident.get("block_number")),
                ("Block hash", ident.get("block_hash")),
                ("Runtime code hash", ident.get("runtime_code_hash")),
                ("Proxy", ident.get("is_proxy")),
                ("Implementation", ident.get("implementation")),
                ("Source status", ident.get("source_status")),
                ("Compiler", ident.get("compiler_version")),
                ("Analyzer", (c.get("analyzer") or {}).get("version")),
            ]
        )
    )

    perms = c.get("permissions") or {}
    story.append(_p("Hook permissions (address bits)", h2))
    story.append(_p(", ".join(perms.get("enabled_flags") or []) or "No permission bits set", body))

    summ = c.get("summary") or {}
    story.append(_p("Findings", h2))
    sev = summ.get("by_severity") or {}
    story.append(_p(" · ".join(f"{k}: {v}" for k, v in sev.items() if v) or "No findings", body))
    for f in c.get("findings", []):
        color = SEV_COLORS.get(f["severity"], "#6b7280")
        block = [
            Paragraph(
                f'<font color="{color}"><b>[{escape(f["severity"].upper())}]</b></font> '
                f'<b>{escape(f["title"])}</b> <font size="7" color="#6b7280">{escape(f["finding_id"])} · '
                f"{escape(f['confidence_basis'])} · {escape(f['status'])}</font>",
                body,
            ),
            _p(f["description"], body),
            _p("Why this severity: " + f["severity_rationale"], small),
        ]
        if f.get("lp_implications"):
            block.append(_p("LP implications: " + f["lp_implications"], small))
        if f.get("remediation"):
            block.append(_p("Remediation: " + f["remediation"], small))
        if f.get("evidence_ids"):
            block.append(_p("Evidence: " + ", ".join(f["evidence_ids"]), small))
        for lim in f.get("limitations") or []:
            block.append(_p("Limitation: " + lim, small))
        block.append(Spacer(1, 4))
        story.append(KeepTogether(block))

    sim = c.get("simulation")
    if sim:
        story.append(_p("Fork simulations", h2))
        story.append(
            _p(
                f"Simulation {sim['simulation_id']} · status {sim['status']} · fork block "
                f"{sim['fork_block']} · harness {(sim.get('harness') or {}).get('digest', '')[:23]}",
                small,
            )
        )
        rows = [["Scenario", "Status", "Reason"]]
        for r in sim["runs"]:
            rows.append(
                [
                    _p(r["scenario_id"], small),
                    Paragraph(
                        f'<font color="{STATUS_COLORS.get(r["status"], "#111827")}">{escape(r["status"])}</font>', small
                    ),
                    _p(r["status_reason"], small),
                ]
            )
        t = Table(rows, colWidths=[38 * mm, 28 * mm, 109 * mm])
        t.setStyle(grid)
        story.append(t)
        for r in sim["runs"]:
            if not r["steps"]:
                continue
            story.append(_p(f"{r['scenario_id']} — steps", h3))
            srows = [["Step", "Expected", "Observed", "Result", "Revert"]]
            for s in r["steps"]:
                srows.append(
                    [
                        _p(s["name"], small),
                        _p(s["lp_expectation"], small),
                        _p(s["observed"], small),
                        _p(s.get("step_status"), small),
                        _p((s.get("revert") or "")[:160], small),
                    ]
                )
            t = Table(srows, colWidths=[48 * mm, 18 * mm, 18 * mm, 24 * mm, 67 * mm], repeatRows=1)
            t.setStyle(grid)
            story.append(t)
            if r.get("repro_command"):
                story.append(Preformatted(r["repro_command"], mono, maxLineLength=120))

    lp = c.get("lp_exposure")
    if lp:
        story.append(_p("LP exposure", h2))
        base = lp.get("baseline") or {}
        story.append(
            kv_table([(k, f"{v.get('value')}  [{v.get('tag')}]") for k, v in base.items() if isinstance(v, dict)])
        )
        eff = lp.get("simulation_effects") or {}
        for b in eff.get("withdrawal_blocked_under", []):
            story.append(
                _p(
                    f"Withdrawal blocked under {b['condition']} (measured): position value "
                    f"{b['position_value_unwithdrawable_token1']} token1 not withdrawable while it holds.",
                    body,
                )
            )
        story.append(_p(lp.get("disclaimer", ""), small))

    if c.get("evidence"):
        story.append(_p("Evidence index", h2))
        rows = [["ID", "Kind", "Basis", "Location / title"]]
        for e in c["evidence"]:
            loc = f"{e['source_file']}:{e['line_start']}-{e['line_end']}" if e.get("source_file") else e["title"]
            rows.append([_p(e["evidence_id"], mono), _p(e["kind"], small), _p(e["basis"], small), _p(loc, small)])
        t = Table(rows, colWidths=[30 * mm, 28 * mm, 22 * mm, 95 * mm], repeatRows=1)
        t.setStyle(grid)
        story.append(t)

    story.append(_p("Assumptions", h2))
    story += [_p("• " + a, body) for a in c.get("assumptions", [])]
    story.append(_p("Limitations", h2))
    story += [_p("• " + a, body) for a in c.get("limitations", [])]

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(15 * mm, 10 * mm, f"HookLens · {ident['hook_address']} · not an audit")
        canvas.drawRightString(195 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        title=f"HookLens report {ident['hook_address']}",
        author="HookLens",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
