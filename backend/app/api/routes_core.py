"""System, chain, resolution, scan, finding and job endpoints."""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.api import schemas as S
from app.api.security import limit_jobs, workspace
from app.chains import get_chain, load_chains
from app.config import get_settings
from app.db.base import get_db, session_scope
from app.db.models import Finding, Job, Scan
from app.errors import AppError, NotFound
from app.jobs.dispatch import get_dispatcher
from app.jobs.manager import TERMINAL, request_cancel
from app.services.evm import validate_address
from app.services.resolver import resolve_contract
from app.services.rpc import RpcClient
from app.services.scan_service import create_scan
from app.simulation import forge_runner
from hooklens.analyzers.permissions import decode, is_valid_hook_address, summarize

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- system


@router.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__, "environment": get_settings().environment}


@router.get("/health/worker", tags=["system"])
def worker_health() -> dict[str, Any]:
    s = get_settings()
    fp = forge_runner.forge_path()
    return {
        "dispatcher": get_dispatcher().health(),
        "forge": {"available": fp is not None},
        "ai": {"enabled": s.ai_enabled, "model": s.ai_model if s.ai_enabled else None},
        "chains": {
            cid: {"rpc_configured": c.rpc_configured, "pool_manager": c.pool_manager}
            for cid, c in load_chains().items()
        },
    }


@router.get("/chains", tags=["system"])
def chains() -> list[dict[str, Any]]:
    return [c.public_dict() for c in load_chains().values()]


# ---------------------------------------------------------------- hooks


@router.get("/permissions/decode", tags=["hooks"])
def decode_permissions(address: str) -> dict[str, Any]:
    addr = validate_address(address, field="address")
    perms = decode(addr)
    valid, reason = is_valid_hook_address(addr)
    return {
        "address": addr,
        **summarize(perms),
        "valid_hook_address": valid,
        "validity_reason": reason,
        "flags": [p.to_dict() for p in perms],
    }


@router.post("/hooks/resolve", tags=["hooks"])
def resolve_hook(body: S.ResolveRequest, _ws: str = Depends(workspace)) -> dict[str, Any]:
    chain = get_chain(body.chain_id)
    with RpcClient(chain) as rpc:
        r = resolve_contract(rpc, chain, body.address, body.block_number)
    perms = decode(r.address)
    return {
        "provenance": r.provenance(),
        "source_status": r.source_status,
        "contract_name": r.source.contract_name,
        "proxy": dataclasses.asdict(r.proxy),
        "permissions": summarize(perms),
        "notes": r.notes,
    }


# ---------------------------------------------------------------- scans


@router.post("/scans", tags=["scans"], status_code=202, response_model=S.ScanOut, dependencies=[Depends(limit_jobs)])
def post_scan(body: S.ScanCreate, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> Scan:
    scan = create_scan(
        db,
        workspace_id=ws,
        chain_id=body.chain_id,
        hook_address=body.hook_address,
        pool_id=body.pool_id,
        block_number=body.block_number,
        options={"discover_pools": body.discover_pools},
    )
    db.refresh(scan)
    return scan


@router.get("/scans", tags=["scans"], response_model=S.Page[S.ScanSummary])
def list_scans(
    db: Session = Depends(get_db),
    ws: str = Depends(workspace),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    chain_id: int | None = None,
    hook_address: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    q = select(Scan).where(Scan.workspace_id == ws)
    if chain_id is not None:
        q = q.where(Scan.chain_id == chain_id)
    if hook_address:
        q = q.where(func.lower(Scan.hook_address) == hook_address.lower())
    if status:
        q = q.where(Scan.status == status)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    items = db.execute(q.order_by(Scan.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def owned_scan(db: Session, ws: str, scan_id: str) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None or scan.workspace_id != ws:
        raise NotFound("scan", scan_id)
    return scan


@router.get("/scans/{scan_id}", tags=["scans"], response_model=S.ScanOut)
def get_scan(scan_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> Scan:
    return owned_scan(db, ws, scan_id)


@router.get("/scans/{scan_id}/findings", tags=["scans"], response_model=list[S.FindingOut])
def get_findings(
    scan_id: str,
    db: Session = Depends(get_db),
    ws: str = Depends(workspace),
    severity: str | None = None,
    category: str | None = None,
    basis: str | None = None,
    status: str | None = None,
) -> list[Finding]:
    from hooklens.analyzers.core import SEVERITY_ORDER, Severity

    owned_scan(db, ws, scan_id)
    q = select(Finding).where(Finding.scan_id == scan_id)
    if severity:
        q = q.where(Finding.severity.in_(severity.split(",")))
    if category:
        q = q.where(Finding.category.in_(category.split(",")))
    if basis:
        q = q.where(Finding.confidence_basis.in_(basis.split(",")))
    if status:
        q = q.where(Finding.status.in_(status.split(",")))
    rows = list(db.execute(q).scalars().all())
    rows.sort(key=lambda f: (SEVERITY_ORDER.get(Severity(f.severity), 9), f.finding_id))
    return rows


@router.get("/scans/{scan_id}/findings/{finding_id}", tags=["scans"], response_model=S.FindingOut)
def get_finding(scan_id: str, finding_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> Finding:
    owned_scan(db, ws, scan_id)
    f = db.execute(
        select(Finding).where(Finding.scan_id == scan_id, Finding.finding_id == finding_id)
    ).scalar_one_or_none()
    if f is None:
        raise NotFound("finding", finding_id)
    return f


# ---------------------------------------------------------------- jobs


def owned_job(db: Session, ws: str, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.workspace_id != ws:
        raise NotFound("job", job_id)
    return job


@router.get("/jobs/{job_id}", tags=["jobs"], response_model=S.JobOut)
def get_job(job_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> Job:
    return owned_job(db, ws, job_id)


@router.post("/jobs/{job_id}/cancel", tags=["jobs"], response_model=S.JobOut)
def cancel_job(job_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> Job:
    job = owned_job(db, ws, job_id)
    if job.status in TERMINAL:
        raise AppError("job_finished", f"The job already finished with status {job.status}.", status_code=409)
    request_cancel(db, job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}/events", tags=["jobs"])
def job_events(
    job_id: str, request: Request, db: Session = Depends(get_db), ws: str = Depends(workspace)
) -> StreamingResponse:
    """Server-sent events: `progress` per job event, then a final `end` event. Resumable via Last-Event-ID."""
    owned_job(db, ws, job_id)
    try:
        start = int(request.headers.get("last-event-id", "-1")) + 1
    except ValueError:
        start = 0

    def stream() -> Iterator[str]:
        sent = start
        last_beat = time.monotonic()
        deadline = time.monotonic() + 3600
        yield "retry: 2000\n\n"
        while time.monotonic() < deadline:
            with session_scope() as s:
                job = s.get(Job, job_id)
                if job is None:
                    yield 'event: end\ndata: {"status": "missing"}\n\n'
                    return
                events = list(job.events or [])
                status, progress, stage = job.status, job.progress, job.stage
                error = job.error
            for i in range(sent, len(events)):
                payload = {**events[i], "status": status}
                yield f"id: {i}\nevent: progress\ndata: {json.dumps(payload, default=str)}\n\n"
            sent = max(sent, len(events))
            if status in TERMINAL:
                end = {"status": status, "progress": progress, "stage": stage, "error": error}
                yield f"event: end\ndata: {json.dumps(end, default=str)}\n\n"
                return
            if time.monotonic() - last_beat > 15:
                yield ": keep-alive\n\n"
                last_beat = time.monotonic()
            time.sleep(0.5)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
