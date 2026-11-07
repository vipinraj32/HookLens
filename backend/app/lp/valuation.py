"""Position valuation with explicit provenance on every number.

Tags:
  live          pool state read from the chain at its latest block (block, hash and time attached)
  historical    pool state from a scan snapshot at its pinned block
  measured      observed in an executed fork simulation (amounts, fees, revert outcomes)
  hypothetical  depends on an assumption or on your inputs: the modelled position, price moves
  unavailable   cannot be computed honestly from the available data (reason given)

The modelled position is never an on-chain LP position: it is what your inputs would hold at the
stated pool state. Its figures are therefore tagged hypothetical even when the pool state is live.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Any

from app.lp import math as lpm
from app.lp.position import Position, fmt_decimal, human_price, to_human
from app.simulation.positions import position_creation, withdrawal_summary

DEFAULT_PRICE_MOVES = (-0.5, -0.2, -0.1, 0.0, 0.1, 0.2, 0.5)

SCENARIO_ASSUMPTIONS = [
    "The pool price moves instantly to the stated level; nothing else changes.",
    "No trading fees are earned and no hook effects are applied.",
    "Hold value keeps the deposited token amounts unchanged.",
]


def _frac_to_human(v: Fraction, decimals: int) -> str:
    return fmt_decimal(Decimal(v.numerator) / Decimal(v.denominator) / Decimal(10**decimals), decimals)


def _tagged(value: Any, tag: str, basis: str, **extra: Any) -> dict[str, Any]:
    return {"value": value, "tag": tag, "basis": basis, **extra}


def baseline(
    pos: Position,
    pool_liquidity: int,
    sym0: str,
    sym1: str,
    *,
    state_tag: str = "historical",
    state_label: str = "at the pinned block",
) -> dict[str, Any]:
    """Pool facts tagged `state_tag` (live or historical); modelled-position figures hypothetical."""
    a0, a1 = pos.deposit()
    value1 = pos.value_in_token1(a0, a1, pos.sqrt_price_x96)
    in_range = pos.range_state() == "in-range"
    share = Fraction(pos.liquidity, pool_liquidity + pos.liquidity) if in_range else Fraction(0)
    model = "modelled position"
    return {
        "price": _tagged(
            fmt_decimal(human_price(pos.sqrt_price_x96, pos.dec0, pos.dec1)),
            state_tag,
            f"slot0.sqrtPriceX96 {state_label} ({sym1} per {sym0})",
        ),
        "price_inverted": _tagged(
            fmt_decimal(1 / human_price(pos.sqrt_price_x96, pos.dec0, pos.dec1)),
            state_tag,
            f"1 / price ({sym0} per {sym1}) {state_label}",
        ),
        "current_tick": _tagged(pos.current_tick, state_tag, f"slot0.tick {state_label}"),
        "pool_active_liquidity": _tagged(str(pool_liquidity), state_tag, f"PoolManager liquidity {state_label}"),
        "range_state": _tagged(pos.range_state(), "hypothetical", f"your range vs the current tick {state_label}"),
        "price_lower": _tagged(
            fmt_decimal(human_price(pos.sqrt_lower, pos.dec0, pos.dec1)),
            "hypothetical",
            "your lower tick, TickMath.getSqrtPriceAtTick",
        ),
        "price_upper": _tagged(
            fmt_decimal(human_price(pos.sqrt_upper, pos.dec0, pos.dec1)),
            "hypothetical",
            "your upper tick, TickMath.getSqrtPriceAtTick",
        ),
        "liquidity": _tagged(str(pos.liquidity), "hypothetical", f"{model}: LiquidityAmounts.getLiquidityForAmounts"),
        "deposit_amount0": _tagged(
            to_human(a0, pos.dec0), "hypothetical", f"{model}: SqrtPriceMath.getAmount0Delta (round up)", raw=str(a0)
        ),
        "deposit_amount1": _tagged(
            to_human(a1, pos.dec1), "hypothetical", f"{model}: SqrtPriceMath.getAmount1Delta (round up)", raw=str(a1)
        ),
        "value_in_token1": _tagged(
            _frac_to_human(value1, pos.dec1),
            "hypothetical",
            f"{model} valued at the price {state_label}: amount0 x price + amount1, in {sym1}",
        ),
        "share_of_active_liquidity": _tagged(
            fmt_decimal(Decimal(share.numerator) / Decimal(share.denominator) * 100, 6) if share else "0",
            "hypothetical",
            "share this modelled position would hold if it were added: L / (pool active L + L), percent; "
            "0 when out of range. It is not an existing share.",
        ),
        "fee_income": _tagged(
            None,
            "unavailable",
            "Future fee income needs future volume, which is not estimated. "
            "Fees observed in a simulation are reported separately as measured.",
        ),
    }


def price_scenarios(pos: Position, moves: tuple[float, ...] = DEFAULT_PRICE_MOVES) -> list[dict[str, Any]]:
    """Hypothetical instantaneous price moves: LP principal vs holding the deposited tokens."""
    a0, a1 = pos.deposit()
    out = []
    for m in moves:
        mult = Decimal(1) + Decimal(str(m))
        if mult <= 0:
            continue
        sp = int((Decimal(pos.sqrt_price_x96) * mult.sqrt()).to_integral_value())
        sp = min(max(sp, lpm.MIN_SQRT_PRICE), lpm.MAX_SQRT_PRICE - 1)
        n0, n1 = pos.amounts_at(sp)
        lp_val = pos.value_in_token1(n0, n1, sp)
        hold_val = pos.value_in_token1(a0, a1, sp)
        div = lp_val - hold_val
        out.append(
            {
                "price_move": m,
                "assumption": f"Price instantly moves {m * 100:+.0f}% with no fees earned and no hook effects",
                "tag": "hypothetical",
                "price": fmt_decimal(human_price(sp, pos.dec0, pos.dec1)),
                "tick": lpm.get_tick_at_sqrt_price(sp),
                "range_state": pos.range_state(lpm.get_tick_at_sqrt_price(sp)),
                "amount0": to_human(n0, pos.dec0),
                "amount1": to_human(n1, pos.dec1),
                "lp_value_token1": _frac_to_human(lp_val, pos.dec1),
                "hold_value_token1": _frac_to_human(hold_val, pos.dec1),
                "divergence_token1": _frac_to_human(div, pos.dec1)
                if div >= 0
                else "-" + _frac_to_human(-div, pos.dec1),
                "divergence_pct": (
                    fmt_decimal(
                        Decimal(div.numerator)
                        / Decimal(div.denominator)
                        / (Decimal(hold_val.numerator) / Decimal(hold_val.denominator))
                        * 100,
                        4,
                    )
                    if hold_val
                    else None
                ),
            }
        )
    return out


def _amt(step: dict[str, Any], k: str) -> int:
    try:
        return int(step.get(k) or 0)
    except (TypeError, ValueError):
        return 0


def simulation_effects(
    sim: Any, pos: Position, value_token1: Fraction, *, state_block: int | None = None
) -> dict[str, Any]:
    """Measured outcomes from a past simulation, and what they imply for this modelled position.

    Withdrawals count as blocked only when the harness held a real position and its removal reverted;
    removals that had no position to remove are reported as not tested.
    """
    if sim is None:
        return {"tag": "unavailable", "reason": "No simulation applied."}
    runs = {r.scenario_id: r for r in sim.runs}
    spec_pos = (sim.spec or {}).get("position") or {}
    same_range = spec_pos.get("tick_lower") == pos.tick_lower and spec_pos.get("tick_upper") == pos.tick_upper
    effects: dict[str, Any] = {
        "source": "historical_simulation",
        "simulation_id": sim.id,
        "status": sim.status,
        "fork_block": sim.fork_block,
        "fork_block_hash": getattr(sim, "fork_block_hash", None),
        "state_block": state_block,
        "blocks_since_simulation": (
            state_block - sim.fork_block if state_block is not None and sim.fork_block is not None else None
        ),
        "simulated_position": {
            "tick_lower": spec_pos.get("tick_lower"),
            "tick_upper": spec_pos.get("tick_upper"),
            "liquidity": spec_pos.get("liquidity"),
        },
        "same_range_as_simulation": same_range,
    }

    wd_summary = withdrawal_summary(runs)
    creation = wd_summary["position_creation"]
    if creation["status"] == "not_attempted":
        # No withdrawal-relevant scenario ran: use any scenario that tried to add liquidity.
        for r in runs.values():
            c = position_creation(list(r.steps or []))
            if c["status"] != "not_attempted":
                creation = {**c, "scenario": r.scenario_id}
                break
    effects["position_creation"] = {**creation, "tag": "measured", "fork_block": sim.fork_block}

    blocked: list[dict[str, Any]] = []
    succeeded: list[str] = []
    recovered: list[str] = []
    not_tested: list[dict[str, Any]] = []
    for o in wd_summary["outcomes"]:
        cond = o["condition"]
        if o["outcome"] == "blocked":
            if not any(x["condition"] == cond for x in blocked):
                blocked.append(
                    {
                        "condition": cond,
                        "scenario": o["scenario"],
                        "step": o["step"],
                        "revert": o["revert"],
                        "tag": "measured",
                        "position_value_unwithdrawable_token1": _frac_to_human(value_token1, pos.dec1),
                        "value_basis": "The harness held a position and its removal reverted entirely, so the full "
                        "value of this modelled position would not be withdrawable while the condition holds.",
                    }
                )
        elif o["outcome"] == "completed" and str(o["step"]).startswith("recover_after_"):
            # Runs after the condition was cleared: evidence of recovery, not of success under it.
            if cond not in recovered:
                recovered.append(cond)
        elif o["outcome"] == "completed":
            if cond not in succeeded:
                succeeded.append(cond)
        else:
            not_tested.append({**o, "reason": "No position was created, so there was nothing to withdraw."})
    effects["withdrawal"] = {
        "status": wd_summary["status"],
        "tag": "measured",
        "unsupported_scenarios": wd_summary["unsupported_scenarios"],
        "execution_error_scenarios": wd_summary["execution_error_scenarios"],
        "outcomes": wd_summary["outcomes"],
    }
    effects["withdrawal_blocked_under"] = blocked
    effects["withdrawal_succeeded_under"] = succeeded
    effects["withdrawal_recovered_after"] = recovered
    effects["withdrawal_not_tested"] = not_tested

    fee = runs.get("fee_escalation")
    if fee is not None and fee.steps:

        def fees(phase: str) -> list[int]:
            return [
                int(s["metrics"]["lp_fee_pips"])
                for s in fee.steps
                if s.get("phase") == phase
                and (s.get("metrics") or {}).get("lp_fee_pips") is not None
                and s.get("observed") == "success"
            ]

        b, a = fees("baseline"), fees("post_update")
        effects["fee"] = {
            "tag": "measured",
            "baseline_fee_pips": max(b) if b else None,
            "max_fee_after_owner_change_pips": max(a) if a else None,
            "basis": "Swap event fee field in the fork",
        }

    wd = runs.get("withdrawal_failure")
    if wd is not None and wd.steps:
        names = {s["name"]: s for s in wd.steps}
        add, part, full = names.get("add_liquidity"), names.get("partial_remove_50pct"), names.get("full_remove")
        if add and part and full and all(x.get("observed") == "success" for x in (add, part, full)):
            net0 = _amt(add, "amount0") + _amt(part, "amount0") + _amt(full, "amount0")
            net1 = _amt(add, "amount1") + _amt(part, "amount1") + _amt(full, "amount1")
            effects["round_trip"] = {
                "tag": "measured",
                "description": "Simulated LP: add, two trader swaps, remove 50%, remove the rest. Net token change "
                "(positive = LP received more than deposited).",
                "net_amount0": to_human(net0, pos.dec0) if net0 >= 0 else "-" + to_human(-net0, pos.dec0),
                "net_amount1": to_human(net1, pos.dec1) if net1 >= 0 else "-" + to_human(-net1, pos.dec1),
                "applies_to_this_position": "only qualitatively unless the range and liquidity match the simulation",
            }
    acc = runs.get("accounting_invariants")
    if acc is not None and acc.status not in ("unsupported", "infra_error", "queued"):
        effects["accounting"] = {
            "tag": "measured",
            "status": acc.status,
            "violations": [s["name"] for s in acc.steps or [] if not s.get("expectation_met", True)],
        }
    return effects
