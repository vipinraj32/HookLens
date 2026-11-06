"""Report and AI explanation endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes_core import owned_scan
from app.api.security import limit_jobs, workspace
from app.config import get_settings
from app.db.base import get_db
from app.db.models import AiExplanation, Finding, Report, Scan
from app.errors import AppError, NotFound
from app.services import ai_service, report_service

router = APIRouter(prefix="/v1")


class ReportCreate(BaseModel):
    simulation_id: str | None = None
    position_id: str | None = None


def _report_out(r: Report, full: bool) -> dict[str, Any]:
    out = {
        "id": r.id,
        "scan_id": r.scan_id,
        "simulation_id": r.simulation_id,
        "position_id": r.position_id,
        "status": r.status,
        "report_version": r.report_version,
        "content_hash": r.content_hash,
        "pdf_available": bool(r.pdf_path),
        "error": r.error,
        "created_at": r.created_at,
    }
    if full:
        out["content"] = r.content
    return out


def _owned_report(db: Session, ws: str, report_id: str) -> Report:
    r = db.get(Report, report_id)
    if r is None or r.workspace_id != ws:
        raise NotFound("report", report_id)
    return r


@router.post("/scans/{scan_id}/reports", tags=["reports"], status_code=202, dependencies=[Depends(limit_jobs)])
def post_report(
    scan_id: str, body: ReportCreate, db: Session = Depends(get_db), ws: str = Depends(workspace)
) -> dict[str, Any]:
    r = report_service.create_report(
        db, workspace_id=ws, scan_id=scan_id, simulation_id=body.simulation_id, position_id=body.position_id
    )
    return _report_out(r, full=False)


@router.get("/scans/{scan_id}/reports", tags=["reports"])
def list_reports(scan_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> list[dict[str, Any]]:
    owned_scan(db, ws, scan_id)
    rows = (
        db.execute(
            select(Report)
            .where(Report.scan_id == scan_id, Report.workspace_id == ws)
            .order_by(Report.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_report_out(r, full=False) for r in rows]


@router.get("/reports", tags=["reports"])
def list_workspace_reports(
    db: Session = Depends(get_db),
    ws: str = Depends(workspace),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    chain_id: int | None = None,
) -> dict[str, Any]:
    """All reports in the caller's workspace, newest first, with the scanned hook's identity."""
    q = select(Report, Scan).join(Scan, Scan.id == Report.scan_id).where(Report.workspace_id == ws)
    if chain_id is not None:
        q = q.where(Scan.chain_id == chain_id)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(Report.created_at.desc()).limit(limit).offset(offset)).all()
    items = [{**_report_out(r, full=False), "chain_id": s.chain_id, "hook_address": s.hook_address} for r, s in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/reports/{report_id}", tags=["reports"])
def get_report(report_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> dict[str, Any]:
    return _report_out(_owned_report(db, ws, report_id), full=True)


@router.get("/reports/{report_id}/pdf", tags=["reports"], response_class=FileResponse)
def get_report_pdf(report_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> FileResponse:
    r = _owned_report(db, ws, report_id)
    if not r.pdf_path:
        raise AppError("pdf_not_ready", f"The PDF is not available (status: {r.status}).", status_code=409)
    path = Path(r.pdf_path).resolve()
    if path.parent != Path(get_settings().reports_dir).resolve() or not path.exists():
        raise NotFound("report file", report_id)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"hooklens-report-{r.content['identity']['hook_address']}-{r.id[:8]}.pdf",
    )


# ---------------------------------------------------------------- AI explanations


def _expl_out(e: AiExplanation) -> dict[str, Any]:
    return {
        "id": e.id,
        "scan_id": e.scan_id,
        "finding_id": e.finding_id,
        "status": e.status,
        "model": e.model,
        "content": e.content,
        "validation": e.validation,
        "created_at": e.created_at,
        "job_id": (e.validation or {}).get("job_id"),
    }


@router.post(
    "/scans/{scan_id}/findings/{finding_id}/explanations",
    tags=["ai"],
    status_code=202,
    dependencies=[Depends(limit_jobs)],
)
def post_explanation(
    scan_id: str, finding_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)
) -> dict[str, Any]:
    scan = owned_scan(db, ws, scan_id)
    f = db.execute(
        select(Finding).where(Finding.scan_id == scan_id, Finding.finding_id == finding_id)
    ).scalar_one_or_none()
    if f is None:
        raise NotFound("finding", finding_id)
    return _expl_out(ai_service.request_explanation(db, workspace_id=ws, scan=scan, finding=f))


@router.get("/scans/{scan_id}/findings/{finding_id}/explanations", tags=["ai"])
def list_explanations(
    scan_id: str, finding_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)
) -> list[dict[str, Any]]:
    owned_scan(db, ws, scan_id)
    rows = (
        db.execute(
            select(AiExplanation)
            .where(AiExplanation.scan_id == scan_id, AiExplanation.finding_id == finding_id)
            .order_by(AiExplanation.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_expl_out(e) for e in rows]
