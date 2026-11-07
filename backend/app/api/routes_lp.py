"""LP exposure endpoints: model a position on a scanned pool and compare it with simulation results.

Two pool-state sources, never mixed silently:
  live        read from the chain at its latest block when the request is made (default)
  historical  the scan's snapshot at its pinned block (state_source="scan")
Simulation effects always come from a past fork run and carry their own fork block.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes_core import owned_scan
from app.api.security import workspace
from app.chains import get_chain
from app.db.base import get_db
from app.db.models import ExposureResult, LpPosition, Scan, Simulation
from app.errors import AppError, NotFound
from app.lp.position import CALCULATION_VERSION, build_position, parse_amount
from app.lp.valuation import (
    DEFAULT_PRICE_MOVES,
    SCENARIO_ASSUMPTIONS,
    baseline,
    price_scenarios,
    simulation_effects,
)
from app.services.live_pool import get_live_pool_service
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
    state_source: Literal["live", "scan"] = Field(
        default="live",
        description="live: read pool state from the chain at its latest block now (fails if it cannot be read; "
        "never falls back). scan: use the scan's historical snapshot at its pinned block.",
    )


DISCLAIMER = (
    "Live figures are pool state read from the chain at the stated block. Historical figures come from a scan "
    "snapshot. Measured figures come from a past fork simulation at its own block. Hypothetical figures depend on "
    "your inputs or a stated assumption; the modelled position is not an on-chain LP position. None of this is a "
    "forecast or financial advice."
)


def _pool_state(scan: Scan, pool: dict[str, Any], source: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(pool state for the math, provenance). Live reads never fall back to the snapshot."""
    if source == "live":
        chain = get_chain(scan.chain_id)
        live = get_live_pool_service().pool_state(chain, pool, hook=scan.hook_address)
        prov = {k: v for k, v in live.items() if k != "state"}
        return live["state"], prov
    st = pool.get("state") or {}
    return st, {
        "source": "historical",
        "chain_id": scan.chain_id,
        "pool_id": pool["pool_id"],
        "block_number": st.get("block_number") or scan.block_number,
        "block_hash": (
            getattr(scan.contract, "block_hash", None)
            if (st.get("block_number") or scan.block_number) == scan.block_number
            else None
        ),
        "block_timestamp": None,
        "block_time": None,
        "fetched_at": scan.created_at.isoformat() if getattr(scan, "created_at", None) else None,
        "basis": "Pool state recorded by the scan at its pinned block.",
    }


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
    state, provenance = _pool_state(scan, pool, body.state_source)
    pos, notes = build_position(
        pool_state=state,
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
    block = provenance.get("block_number")
    is_live = provenance["source"] == "live"
    base = baseline(
        pos,
        int(state.get("liquidity") or 0),
        sym0,
        sym1,
        state_tag="live" if is_live else "historical",
        state_label=f"at {'live' if is_live else 'scan'} block {block}",
    )
    da0, da1 = pos.deposit()
    value1 = pos.value_in_token1(da0, da1, pos.sqrt_price_x96)
    moves = tuple(body.price_moves) if body.price_moves else DEFAULT_PRICE_MOVES
    effects = simulation_effects(sim, pos, value1, state_block=block)
    creation = effects.get("position_creation") or {}
    position_kind = {
        "kind": "modelled",
        "note": "A position modelled from your inputs. It is not an on-chain LP position.",
        "deposit_rejected_in_simulation": creation.get("status") == "rejected",
        "rejection": (
            {"step": creation.get("step"), "revert": creation.get("revert"), "fork_block": creation.get("fork_block")}
            if creation.get("status") == "rejected"
            else None
        ),
    }
    result = {
        "calculation_version": CALCULATION_VERSION,
        "pool": {
            "pool_id": pool["pool_id"],
            "token0": t0,
            "token1": t1,
            "fee": pool.get("fee"),
            "tick_spacing": pool.get("tick_spacing"),
            "state": state,
            "block_number": block,
        },
        "data_source": provenance,
        "position": {"tick_lower": pos.tick_lower, "tick_upper": pos.tick_upper, "liquidity": str(pos.liquidity)},
        "notes": notes,
        "baseline": base,
        "price_scenarios": price_scenarios(pos, moves),
        "scenario_assumptions": SCENARIO_ASSUMPTIONS,
        "simulation_effects": effects,
        "position_kind": position_kind,
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


@router.get("/scans/{scan_id}/pools/{pool_id}/live")
def live_pool_state(
    scan_id: str, pool_id: str, refresh: bool = False, db: Session = Depends(get_db), ws: str = Depends(workspace)
) -> dict[str, Any]:
    """Current pool state at the chain's latest block, with block number, hash, time and fetch time.

    The pool must belong to the scan (and so to its hook and chain). `refresh=true` bypasses the
    short head cache; state for a given block is immutable and stays cached.
    """
    scan = owned_scan(db, ws, scan_id)
    pool = select_pool(list(scan.pools or []), pool_id)
    chain = get_chain(scan.chain_id)
    live = get_live_pool_service().pool_state(chain, pool, hook=scan.hook_address, force=refresh)
    t0, t1 = pool.get("token0") or {}, pool.get("token1") or {}
    dec0, dec1 = t0.get("decimals"), t1.get("decimals")
    price = None
    if dec0 is not None and dec1 is not None:
        from app.lp.position import fmt_decimal, human_price

        hp = human_price(int(live["state"]["sqrt_price_x96"]), int(dec0), int(dec1))
        price = {"token1_per_token0": fmt_decimal(hp), "token0_per_token1": fmt_decimal(1 / hp)}
    return {
        **live,
        "price": price,
        "token0": {"symbol": t0.get("symbol"), "decimals": dec0, "address": pool.get("currency0")},
        "token1": {"symbol": t1.get("symbol"), "decimals": dec1, "address": pool.get("currency1")},
        "scan_block_number": scan.block_number,
    }


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
