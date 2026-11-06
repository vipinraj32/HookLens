"""Reports: a versioned, content-hashed JSON document and a PDF rendering of it."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.db.base import session_scope
from app.db.models import Contract, Evidence, ExposureResult, Finding, LpPosition, Report, Scan, Simulation
from app.errors import AppError, NotFound
from app.jobs.dispatch import get_dispatcher
from app.jobs.manager import JobContext, create_job, on_terminal, register
from app.simulation.interpret import findings_for_simulation
from hooklens.analyzers.core import SEVERITY_ORDER, Severity

REPORT_VERSION = "1.0.0"
DISCLAIMER = (
    "HookLens reports present deterministic analysis and fork-simulation results for the exact configuration "
    "recorded below. They are not a security audit, do not establish that a hook is safe, and are not financial "
    "advice. Findings marked 'inferred' come from static analysis; 'observed' findings were reproduced in a fork."
)
LIMITATIONS = [
    "Static analysis covers the verified or locally matched source only; bytecode-only contracts get permission "
    "and bytecode checks only.",
    "Simulations run one pool at one pinned block with the recorded parameters; other states may behave differently.",
    "Adverse conditions (oracle failure, pause, upgrades) are induced with Foundry cheatcodes in a local fork.",
    "Hypothetical LP figures depend on the stated price assumptions and exclude fees unless measured.",
]


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def build_content(db: Session, scan: Scan, sim: Simulation | None, position: LpPosition | None) -> dict[str, Any]:
    contract = db.get(Contract, scan.contract_id) if scan.contract_id else None
    findings = sorted(
        db.execute(select(Finding).where(Finding.scan_id == scan.id)).scalars().all(),
        key=lambda f: (SEVERITY_ORDER.get(Severity(f.severity), 9), f.finding_id),
    )
    # Static findings come from the scan; observed findings are re-derived from this simulation's own
    # runs, so a report always reflects exactly the simulation it names.
    static = [_finding_dict(f) for f in findings if f.simulation_id is None]
    observed: list[dict[str, Any]] = []
    sim_evidence: list[dict[str, Any]] = []
    if sim is not None:
        col = findings_for_simulation(scan.hook_address, sim)
        observed = [
            _finding_dict(f)
            for f in sorted(col.findings.values(), key=lambda f: (SEVERITY_ORDER[f.severity], f.finding_id))
        ]
        sim_evidence = [
            {
                "evidence_id": e.evidence_id,
                "kind": e.kind,
                "title": e.title,
                "basis": e.basis.value,
                "source_file": None,
                "line_start": None,
                "line_end": None,
                "function_name": None,
                "excerpt": None,
            }
            for e in col.evidence.values()
        ]
    ev_ids = {e for f in static for e in (f["evidence_ids"] or [])}
    evidence = (
        db.execute(select(Evidence).where(Evidence.scan_id == scan.id, Evidence.evidence_id.in_(ev_ids)))
        .scalars()
        .all()
        if ev_ids
        else []
    )
    exposure = None
    if position is not None:
        res = (
            db.execute(
                select(ExposureResult)
                .where(ExposureResult.position_id == position.id)
                .order_by(ExposureResult.created_at.desc())
            )
            .scalars()
            .first()
        )
        exposure = {"position_id": position.id, "params": position.params, **(res.result if res else {})}
    sim_block = None
    if sim is not None:
        sim_block = {
            "simulation_id": sim.id,
            "status": sim.status,
            "fork_block": sim.fork_block,
            "fork_block_hash": sim.fork_block_hash,
            "harness": (sim.spec or {}).get("harness"),
            "position": (sim.spec or {}).get("position"),
            "privileged_actor": (sim.spec or {}).get("privileged_actor"),
            "runs": [
                {
                    "scenario_id": r.scenario_id,
                    "status": r.status,
                    "status_reason": r.status_reason,
                    "duration_ms": r.duration_ms,
                    "repro_command": r.repro_command,
                    "notes": (r.parameters or {}).get("notes", []),
                    "steps": [
                        {
                            k: s.get(k)
                            for k in (
                                "name",
                                "phase",
                                "condition",
                                "lp_expectation",
                                "observed",
                                "step_status",
                                "privileged",
                                "amount0",
                                "amount1",
                                "gas_used",
                            )
                        }
                        | {"revert": (s.get("revert") or {}).get("message")}
                        for s in r.steps or []
                    ],
                }
                for r in sim.runs
            ],
        }
    return {
        "report_version": REPORT_VERSION,
        "generator": f"HookLens {__version__}",
        "generated_at": datetime.now(UTC).isoformat(),
        "identity": {
            "chain_id": scan.chain_id,
            "hook_address": scan.hook_address,
            "block_number": scan.block_number,
            "block_hash": getattr(contract, "block_hash", None),
            "runtime_code_hash": getattr(contract, "runtime_code_hash", None),
            "contract_name": getattr(contract, "contract_name", None),
            "is_proxy": getattr(contract, "is_proxy", None),
            "implementation": getattr(contract, "implementation_address", None),
            "source_status": getattr(contract, "source_status", None),
            "compiler_version": getattr(contract, "compiler_version", None),
        },
        "provenance": getattr(contract, "provenance", None),
        "analyzer": {
            "version": (scan.analysis or {}).get("analyzer_version"),
            "runs": (scan.analysis or {}).get("runs"),
            "capabilities": (scan.analysis or {}).get("capabilities"),
        },
        "permissions": scan.permissions,
        "pools": [
            {k: p.get(k) for k in ("pool_id", "currency0", "currency1", "fee", "tick_spacing", "state")}
            for p in scan.pools or []
        ],
        "summary": scan.summary,
        "findings": sorted(
            static + observed, key=lambda f: (SEVERITY_ORDER.get(Severity(f["severity"]), 9), f["finding_id"])
        ),
        "evidence": [
            {
                k: getattr(e, k)
                for k in (
                    "evidence_id",
                    "kind",
                    "title",
                    "basis",
                    "source_file",
                    "line_start",
                    "line_end",
                    "function_name",
                )
            }
            | {"excerpt": (e.data or {}).get("excerpt")}
            for e in evidence
        ]
        + sim_evidence,
        "simulation": sim_block,
        "lp_exposure": exposure,
        "assumptions": [
            "Privileged actions are executed by impersonating the detected owner inside the fork; no keys are used.",
            "Token balances for simulation actors are created with Foundry `deal`.",
        ],
        "reproduction": {
            "scan": f"POST /v1/scans {{chain_id: {scan.chain_id}, hook_address: {scan.hook_address}, "
            f"block_number: {scan.block_number}}}",
            "scenarios": [
                r["repro_command"]
                for r in cast(list[dict[str, Any]], (sim_block or {}).get("runs", []))
                if r["repro_command"]
            ],
        },
        "limitations": LIMITATIONS,
        "disclaimer": DISCLAIMER,
    }


_FINDING_FIELDS = (
    "finding_id",
    "title",
    "severity",
    "severity_rationale",
    "confidence_basis",
    "status",
    "category",
    "description",
    "affected_functions",
    "evidence_ids",
    "related_scenarios",
    "lp_implications",
    "remediation",
    "limitations",
)


def _finding_dict(f: Any) -> dict[str, Any]:
    d = {k: getattr(f, k) for k in _FINDING_FIELDS}
    for k in ("severity", "confidence_basis", "status"):
        d[k] = getattr(d[k], "value", d[k])
    return d


def create_report(
    db: Session, *, workspace_id: str, scan_id: str, simulation_id: str | None, position_id: str | None
) -> Report:
    scan = db.get(Scan, scan_id)
    if scan is None or scan.workspace_id != workspace_id:
        raise NotFound("scan", scan_id)
    if scan.status not in ("completed", "partial"):
        raise AppError("scan_not_ready", "Reports need a completed scan.", status_code=409)
    sim = db.get(Simulation, simulation_id) if simulation_id else None
    if simulation_id and (sim is None or sim.scan_id != scan.id):
        raise NotFound("simulation", simulation_id)
    pos = db.get(LpPosition, position_id) if position_id else None
    if position_id and (pos is None or pos.workspace_id != workspace_id):
        raise NotFound("position", position_id)
    content = build_content(db, scan, sim, pos)
    digest = (
        "sha256:" + hashlib.sha256(_canonical({k: v for k, v in content.items() if k != "generated_at"})).hexdigest()
    )
    rep = Report(
        workspace_id=workspace_id,
        scan_id=scan.id,
        simulation_id=sim.id if sim else None,
        position_id=pos.id if pos else None,
        status="rendering",
        report_version=REPORT_VERSION,
        content=content,
        content_hash=digest,
    )
    db.add(rep)
    db.flush()
    job = create_job(
        db,
        kind="report",
        workspace_id=workspace_id,
        subject_id=rep.id,
        payload={"report_id": rep.id},
        timeout_s=120,
        max_attempts=2,
    )
    db.commit()
    get_dispatcher().dispatch(job.id)
    return rep


@on_terminal("report")
def _report_terminal(payload: dict[str, Any], status: str, error: dict[str, Any] | None) -> None:
    with session_scope() as db:
        rep = db.get(Report, payload.get("report_id"))
        if rep and rep.status == "rendering":
            rep.status, rep.error = "pdf_failed", error


@register("report")
def run_report_job(jc: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as db:
        rep = db.get(Report, payload["report_id"])
        if rep is None:
            raise NotFound("report", payload["report_id"])
        content, rid, digest = dict(rep.content), rep.id, rep.content_hash
    jc.update("rendering", 0.3, "Rendering PDF")
    out_dir = Path(get_settings().reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{rid}.pdf"
    from app.reports.pdf import render_pdf

    render_pdf(content, digest, path)
    with session_scope() as db:
        rep = db.get(Report, rid)
        assert rep is not None
        rep.pdf_path, rep.status = str(path), "ready"
    return {"message": "Report ready", "report_id": rid}
