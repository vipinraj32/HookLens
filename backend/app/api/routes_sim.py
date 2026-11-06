"""Simulation and evidence endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import schemas as S
from app.api.routes_core import owned_scan
from app.api.security import limit_jobs, workspace
from app.db.base import get_db
from app.db.models import Evidence, ScenarioRun, Simulation
from app.errors import NotFound
from app.services import simulation_service as sims
from app.simulation.catalog import DEFAULT_ORDER, SCENARIOS

router = APIRouter(prefix="/v1")


@router.get("/scenarios", tags=["simulations"], response_model=list[S.ScenarioDefOut])
def scenarios() -> list[dict[str, Any]]:
    return [
        {"scenario_id": s.scenario_id, "title": s.title, "description": s.description, "executes": list(s.executes)}
        for s in (SCENARIOS[k] for k in DEFAULT_ORDER)
    ]


@router.post(
    "/scans/{scan_id}/simulations",
    tags=["simulations"],
    status_code=202,
    response_model=S.SimulationOut,
    dependencies=[Depends(limit_jobs)],
)
def post_simulation(
    scan_id: str, body: S.SimulationCreate, db: Session = Depends(get_db), ws: str = Depends(workspace)
) -> Simulation:
    owned_scan(db, ws, scan_id)
    opts = body.model_dump(exclude_none=True)
    for k in ("amount0", "amount1", "liquidity", "swap_amount0", "swap_amount1"):
        if k in opts:
            opts[k] = int(opts[k])
    sim = sims.create_simulation(db, workspace_id=ws, scan_id=scan_id, options=opts)
    db.refresh(sim)
    return sim


@router.get("/scans/{scan_id}/simulations", tags=["simulations"], response_model=list[S.SimulationOut])
def list_simulations(scan_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> list[Simulation]:
    owned_scan(db, ws, scan_id)
    return sims.list_simulations(db, ws, scan_id)


@router.get("/simulations/{sim_id}", tags=["simulations"], response_model=S.SimulationOut)
def get_simulation(sim_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> Simulation:
    return sims.get_simulation(db, ws, sim_id)


@router.get("/simulations/{sim_id}/runs/{run_id}", tags=["simulations"], response_model=S.ScenarioRunOut)
def get_run(sim_id: str, run_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> ScenarioRun:
    sims.get_simulation(db, ws, sim_id)
    run = db.get(ScenarioRun, run_id)
    if run is None or run.simulation_id != sim_id:
        raise NotFound("scenario run", run_id)
    return run


@router.get("/evidence", tags=["evidence"], response_model=S.Page[S.EvidenceOut])
def search_evidence(
    scan_id: str,
    db: Session = Depends(get_db),
    ws: str = Depends(workspace),
    q: str | None = Query(None, max_length=200),
    kind: str | None = None,
    basis: str | None = None,
    function: str | None = None,
    simulation_id: str | None = None,
    ids: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    owned_scan(db, ws, scan_id)
    stmt = select(Evidence).where(Evidence.scan_id == scan_id)
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(
            or_(
                Evidence.title.ilike(like),
                Evidence.evidence_id.ilike(like),
                Evidence.function_name.ilike(like),
                Evidence.source_file.ilike(like),
            )
        )
    if kind:
        stmt = stmt.where(Evidence.kind.in_(kind.split(",")))
    if basis:
        stmt = stmt.where(Evidence.basis.in_(basis.split(",")))
    if function:
        stmt = stmt.where(Evidence.function_name == function)
    if simulation_id:
        stmt = stmt.where(Evidence.simulation_id == simulation_id)
    if ids:
        stmt = stmt.where(Evidence.evidence_id.in_(ids.split(",")[:200]))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Evidence.kind, Evidence.evidence_id).limit(limit).offset(offset)).scalars().all()
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/evidence/{scan_id}/{evidence_id}", tags=["evidence"], response_model=S.EvidenceOut)
def get_evidence(
    scan_id: str, evidence_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)
) -> Evidence:
    owned_scan(db, ws, scan_id)
    ev = db.execute(
        select(Evidence).where(Evidence.scan_id == scan_id, Evidence.evidence_id == evidence_id)
    ).scalar_one_or_none()
    if ev is None:
        raise NotFound("evidence", evidence_id)
    return ev
