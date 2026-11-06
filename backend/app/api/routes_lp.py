"""LP exposure endpoints: model a position on a scanned pool and compare it with simulation results."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes_core import owned_scan
from app.api.security import workspace
from app.db.base import get_db
from app.db.models import ExposureResult, LpPosition, Simulation
from app.errors import AppError, NotFound
from app.lp.position import CALCULATION_VERSION, build_position, parse_amount
from app.lp.valuation import DEFAULT_PRICE_MOVES, baseline, price_scenarios, simulation_effects
from app.simulation.planner import select_pool

router = APIRouter(prefix="/v1", tags=["lp"])
_DEC = r"^[0-9]{1,40}(\.[0-9]{1,40})?$"
_INT = r"^[0-9]{1,78}$"


class CompareRequest(BaseModel):
    scan_id: str
    pool_id: str | None = Field(default=None, min_length=66, max_length=66)
    simulation_id: str | None = None
    tick_lower: int | None = Field(default=None, ge=-887272, le=887272)
    tick_upper: int | None = Field(default=None, ge=-887272, le=887272)
    price_lower: str | None = Field(default=None, pattern=_DEC, description="token1 per token0")
    price_upper: str | None = Field(default=None, pattern=_DEC, description="token1 per token0")
    amount0: str | None = Field(default=None, pattern=_DEC, description="token0, human units")
    amount1: str | None = Field(default=None, pattern=_DEC, description="token1, human units")
    amount0_raw: str | None = Field(default=None, pattern=_INT)
    amount1_raw: str | None = Field(default=None, pattern=_INT)
    liquidity: str | None = Field(default=None, pattern=r"^[0-9]{1,39}$")
    price_moves: list[Annotated[float, Field(gt=-1, le=100)]] | None = Field(
        default=None, max_length=21, description="Fractional price moves, e.g. -0.2 for -20%. Must be > -1."
    )
    price_orientation: Literal["token1_per_token0", "token0_per_token1"] = Field(
        default="token1_per_token0",
        description="How price_lower/price_upper are quoted. token0_per_token1 inverts them (and swaps bounds).",
    )


DISCLAIMER = (
    "Figures tagged on-chain are exact v4 math on state read at the pinned block. Measured figures come from fork "
    "simulations under the recorded parameters. Hypothetical figures depend on the stated assumption. None of this "
    "is a forecast or financial advice."
)


def _compare(db: Session, ws: str, body: CompareRequest) -> dict[str, Any]:
    scan = owned_scan(db, ws, body.scan_id)
    pool = select_pool(list(scan.pools or []), body.pool_id)
    t0, t1 = pool.get("token0") or {}, pool.get("token1") or {}
    dec0, dec1 = t0.get("decimals"), t1.get("decimals")
    sym0, sym1 = t0.get("symbol") or "token0", t1.get("symbol") or "token1"
    a0 = int(body.amount0_raw) if body.amount0_raw else parse_amount(body.amount0, dec0, "amount0")
    a1 = int(body.amount1_raw) if body.amount1_raw else parse_amount(body.amount1, dec1, "amount1")
    price_lower, price_upper = body.price_lower, body.price_upper
    if body.price_orientation == "token0_per_token1" and (price_lower or price_upper):
        if not (price_lower and price_upper):
            raise AppError("range_required", "Inverted price ranges need both bounds.", status_code=422)
        if Decimal(price_lower) <= 0 or Decimal(price_upper) <= 0:
            raise AppError("invalid_price", "Prices must be positive.", status_code=422)
        price_lower, price_upper = str(1 / Decimal(price_upper)), str(1 / Decimal(price_lower))
    pos, notes = build_position(
        pool_state=pool.get("state") or {},
        tick_spacing=int(pool["tick_spacing"]),
        dec0=dec0,
        dec1=dec1,
        tick_lower=body.tick_lower,
        tick_upper=body.tick_upper,
        price_lower=price_lower,
        price_upper=price_upper,
        amount0=a0,
        amount1=a1,
        liquidity=int(body.liquidity) if body.liquidity else None,
        sym0=sym0,
        sym1=sym1,
    )
    sim = None
    if body.simulation_id:
        sim = db.get(Simulation, body.simulation_id)
        if sim is None or sim.workspace_id != ws or sim.scan_id != scan.id:
            raise NotFound("simulation", body.simulation_id)
        if sim.pool_id and sim.pool_id.lower() != pool["pool_id"].lower():
            raise AppError(
                "pool_mismatch", "The simulation ran on a different pool than the selected one.", status_code=422
            )
    base = baseline(pos, int((pool.get("state") or {}).get("liquidity") or 0), sym0, sym1)
    da0, da1 = pos.deposit()
    value1 = pos.value_in_token1(da0, da1, pos.sqrt_price_x96)
    moves = tuple(body.price_moves) if body.price_moves else DEFAULT_PRICE_MOVES
    result = {
        "calculation_version": CALCULATION_VERSION,
        "pool": {
            "pool_id": pool["pool_id"],
            "token0": t0,
            "token1": t1,
            "fee": pool.get("fee"),
            "tick_spacing": pool.get("tick_spacing"),
            "state": pool.get("state"),
            "block_number": scan.block_number,
        },
        "position": {"tick_lower": pos.tick_lower, "tick_upper": pos.tick_upper, "liquidity": str(pos.liquidity)},
        "notes": notes,
        "baseline": base,
        "price_scenarios": price_scenarios(pos, moves),
        "simulation_effects": simulation_effects(sim, pos, value1),
        "disclaimer": DISCLAIMER,
    }
    lp = LpPosition(
        workspace_id=ws,
        scan_id=scan.id,
        chain_id=scan.chain_id,
        pool_id=pool["pool_id"],
        params=body.model_dump(exclude_none=True),
        baseline=base,
        calculation_version=CALCULATION_VERSION,
    )
    db.add(lp)
    db.flush()
    db.add(ExposureResult(position_id=lp.id, simulation_id=sim.id if sim else None, result=result))
    db.commit()
    return {"position_id": lp.id, **result}


@router.post("/positions/compare")
def compare(body: CompareRequest, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> dict[str, Any]:
    return _compare(db, ws, body)


@router.get("/positions/{position_id}")
def get_position(position_id: str, db: Session = Depends(get_db), ws: str = Depends(workspace)) -> dict[str, Any]:
    lp = db.get(LpPosition, position_id)
    if lp is None or lp.workspace_id != ws:
        raise NotFound("position", position_id)
    from sqlalchemy import select

    res = (
        db.execute(
            select(ExposureResult).where(ExposureResult.position_id == lp.id).order_by(ExposureResult.created_at.desc())
        )
        .scalars()
        .first()
    )
    return {"position_id": lp.id, "params": lp.params, **(res.result if res else {})}
