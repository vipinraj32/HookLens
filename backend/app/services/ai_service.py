"""Evidence-grounded AI explanations for findings (optional; requires an Anthropic API key)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.graph import GRAPH_VERSION, run_explanation
from app.ai.provider import AnthropicProvider, LlmProvider
from app.config import get_settings
from app.db.base import session_scope
from app.db.models import AiExplanation, Evidence, Finding, Scan, ScenarioRun
from app.errors import NotFound
from app.jobs.dispatch import get_dispatcher
from app.jobs.manager import JobContext, create_job, on_terminal, register

_provider_factory: Callable[[], LlmProvider] = AnthropicProvider
MAX_EVIDENCE_CHARS = 6000


def set_provider_factory(factory: Callable[[], LlmProvider] | None) -> None:
    """Tests inject a fake provider; None restores the Anthropic provider."""
    global _provider_factory
    _provider_factory = factory or AnthropicProvider


def _trim(v: Any, limit: int = MAX_EVIDENCE_CHARS) -> Any:
    s = json.dumps(v, default=str)
    return v if len(s) <= limit else {"_truncated": True, "preview": s[:limit]}


def build_context(db: Session, scan: Scan, finding: Finding) -> dict[str, Any]:
    rows = (
        db.execute(
            select(Evidence).where(Evidence.scan_id == scan.id, Evidence.evidence_id.in_(finding.evidence_ids or []))
        )
        .scalars()
        .all()
    )
    evidence = {
        e.evidence_id: {
            "evidence_id": e.evidence_id,
            "kind": e.kind,
            "title": e.title,
            "basis": e.basis,
            "source_file": e.source_file,
            "line_start": e.line_start,
            "line_end": e.line_end,
            "function_name": e.function_name,
            "data": _trim(e.data),
        }
        for e in rows
    }
    steps: list[dict[str, Any]] = []
    for e in rows:
        st = (e.data or {}).get("step")
        if e.kind == "simulation_step" and st:
            steps.append(
                {
                    "scenario": e.data.get("scenario"),
                    "step": st.get("name"),
                    "observed": st.get("observed"),
                    "lp_expectation": st.get("lp_expectation"),
                    "revert": (st.get("revert") or {}).get("message"),
                }
            )
    if finding.related_scenarios and not steps:
        runs = (
            db.execute(
                select(ScenarioRun)
                .join(ScenarioRun.simulation)
                .where(ScenarioRun.scenario_id.in_(finding.related_scenarios))
            )
            .scalars()
            .all()
        )
        for r in runs:
            if r.simulation.scan_id != scan.id:
                continue
            for st in (r.steps or [])[:40]:
                steps.append(
                    {
                        "scenario": r.scenario_id,
                        "step": st.get("name"),
                        "observed": st.get("observed"),
                        "lp_expectation": st.get("lp_expectation"),
                        "revert": (st.get("revert") or {}).get("message"),
                    }
                )
    fnd = {
        k: getattr(finding, k)
        for k in (
            "finding_id",
            "title",
            "severity",
            "severity_rationale",
            "confidence_basis",
            "status",
            "category",
            "description",
            "affected_functions",
            "lp_implications",
            "remediation",
            "limitations",
        )
    }
    ctx = {
        "finding": fnd,
        "evidence": evidence,
        "simulation_steps": steps,
        "hook": {
            "chain_id": scan.chain_id,
            "address": scan.hook_address,
            "block_number": scan.block_number,
            "permissions": (scan.permissions or {}).get("enabled_flags"),
        },
    }
    ctx["facts_text"] = json.dumps({k: v for k, v in ctx.items()}, default=str)
    return ctx


def request_explanation(db: Session, *, workspace_id: str, scan: Scan, finding: Finding) -> AiExplanation:
    s = get_settings()
    row = AiExplanation(scan_id=scan.id, finding_id=finding.finding_id, status="queued", model=s.ai_model)
    db.add(row)
    db.flush()
    if not s.ai_enabled and _provider_factory is AnthropicProvider:
        row.status = "unavailable"
        row.model = None
        row.validation = {
            "reason": "AI explanations are disabled: HOOKLENS_ANTHROPIC_API_KEY is not configured. "
            "All deterministic findings and evidence remain available."
        }
        db.commit()
        return row
    job = create_job(
        db,
        kind="explain",
        workspace_id=workspace_id,
        subject_id=row.id,
        payload={"explanation_id": row.id},
        timeout_s=int(s.ai_timeout_s * 6),
        max_attempts=2,
    )
    row.validation = {"job_id": job.id}
    db.commit()
    get_dispatcher().dispatch(job.id)
    return row


@on_terminal("explain")
def _explain_terminal(payload: dict[str, Any], status: str, error: dict[str, Any] | None) -> None:
    with session_scope() as db:
        row = db.get(AiExplanation, payload.get("explanation_id"))
        if row and row.status in ("queued", "running"):
            row.status = "error" if status == "failed" else status
            row.validation = {**(row.validation or {}), "error": error}


@register("explain")
def run_explain_job(jc: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as db:
        row = db.get(AiExplanation, payload["explanation_id"])
        if row is None:
            raise NotFound("explanation", payload["explanation_id"])
        row.status = "running"
        scan = db.get(Scan, row.scan_id)
        finding = db.execute(
            select(Finding).where(Finding.scan_id == row.scan_id, Finding.finding_id == row.finding_id)
        ).scalar_one_or_none()
        if scan is None or finding is None:
            raise NotFound("finding", row.finding_id)
        ctx = build_context(db, scan, finding)
    jc.update(
        "collecting",
        0.1,
        f"Collected {len(ctx['evidence'])} evidence item(s) and {len(ctx['simulation_steps'])} simulation step(s)",
    )
    provider = _provider_factory()
    jc.update("generating", 0.3, f"Generating explanation with {provider.model}")
    state = run_explanation(provider, ctx)
    jc.check()
    status = state["status"]
    with session_scope() as db:
        row = db.get(AiExplanation, payload["explanation_id"])
        assert row is not None
        row.status = status
        row.model = provider.model
        row.content = (
            {
                "graph_version": GRAPH_VERSION,
                "technical": t.model_dump() if (t := state.get("technical")) else None,
                "lp": lp.model_dump() if (lp := state.get("lp")) else None,
                "attempts": state.get("attempts"),
            }
            if status == "ready"
            else {"graph_version": GRAPH_VERSION, "attempts": state.get("attempts")}
        )
        row.validation = {**(row.validation or {}), **state["validation"]}
    jc.update(
        "done",
        1.0,
        "Explanation accepted by the validator"
        if status == "ready"
        else "Explanation rejected by the validator; not shown",
    )
    return {"message": f"Explanation {status}", "status": status}
