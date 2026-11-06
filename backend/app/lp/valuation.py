"""Position valuation with explicit provenance on every number.

Tags:
  on-chain      read from chain state at the pinned block (pool price, liquidity) or derived
                from it with exact v4 math
  measured      taken from an executed simulation run (amounts, fees, revert outcomes)
  hypothetical  depends on an assumption stated next to it (e.g. a price move)
  unavailable   cannot be computed honestly from the available data (reason given)
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Any

from app.lp import math as lpm
from app.lp.position import Position, fmt_decimal, human_price, to_human

DEFAULT_PRICE_MOVES = (-0.5, -0.2, -0.1, 0.0, 0.1, 0.2, 0.5)


def _frac_to_human(v: Fraction, decimals: int) -> str:
    return fmt_decimal(Decimal(v.numerator) / Decimal(v.denominator) / Decimal(10**decimals), decimals)


def _tagged(value: Any, tag: str, basis: str, **extra: Any) -> dict[str, Any]:
    return {"value": value, "tag": tag, "basis": basis, **extra}


def baseline(pos: Position, pool_liquidity: int, sym0: str, sym1: str) -> dict[str, Any]:
    a0, a1 = pos.deposit()
    value1 = pos.value_in_token1(a0, a1, pos.sqrt_price_x96)
    in_range = pos.range_state() == "in-range"
    share = Fraction(pos.liquidity, pool_liquidity + pos.liquidity) if in_range else Fraction(0)
    return {
        "range_state": _tagged(pos.range_state(), "on-chain", "current tick vs position ticks"),
        "price": _tagged(
            fmt_decimal(human_price(pos.sqrt_price_x96, pos.dec0, pos.dec1)),
            "on-chain",
            f"slot0.sqrtPriceX96 at pinned block ({sym1} per {sym0})",
        ),
        "price_inverted": _tagged(
            fmt_decimal(1 / human_price(pos.sqrt_price_x96, pos.dec0, pos.dec1)),
            "on-chain",
            f"1 / price ({sym0} per {sym1})",
        ),
        "price_lower": _tagged(
            fmt_decimal(human_price(pos.sqrt_lower, pos.dec0, pos.dec1)),
            "on-chain",
            "TickMath.getSqrtPriceAtTick(tick_lower)",
        ),
        "price_upper": _tagged(
            fmt_decimal(human_price(pos.sqrt_upper, pos.dec0, pos.dec1)),
            "on-chain",
            "TickMath.getSqrtPriceAtTick(tick_upper)",
        ),
        "liquidity": _tagged(str(pos.liquidity), "on-chain", "LiquidityAmounts.getLiquidityForAmounts"),
        "deposit_amount0": _tagged(
            to_human(a0, pos.dec0), "on-chain", "SqrtPriceMath.getAmount0Delta (round up)", raw=str(a0)
        ),
        "deposit_amount1": _tagged(
            to_human(a1, pos.dec1), "on-chain", "SqrtPriceMath.getAmount1Delta (round up)", raw=str(a1)
        ),
        "value_in_token1": _tagged(
            _frac_to_human(value1, pos.dec1), "on-chain", f"amount0 x price + amount1, in {sym1}"
        ),
        "share_of_active_liquidity": _tagged(
            fmt_decimal(Decimal(share.numerator) / Decimal(share.denominator) * 100, 6) if share else "0",
            "on-chain",
            "position L / (pool active L + position L), percent; 0 when out of range",
        ),
        "fee_income": _tagged(
            None,
            "unavailable",
            "Fee income requires future volume, which is not estimated. "
            "Measured fees from simulation runs are reported separately.",
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


def simulation_effects(sim: Any, pos: Position, value_token1: Fraction) -> dict[str, Any]:
    """Measured outcomes from a simulation, and what they imply for this position."""
    if sim is None:
        return {"tag": "unavailable", "reason": "No simulation selected. Run the Adversarial Lab to measure effects."}
    runs = {r.scenario_id: r for r in sim.runs}
    spec_pos = (sim.spec or {}).get("position") or {}
    same_range = spec_pos.get("tick_lower") == pos.tick_lower and spec_pos.get("tick_upper") == pos.tick_upper
    effects: dict[str, Any] = {
        "simulation_id": sim.id,
        "status": sim.status,
        "fork_block": sim.fork_block,
        "simulated_position": {
            "tick_lower": spec_pos.get("tick_lower"),
            "tick_upper": spec_pos.get("tick_upper"),
            "liquidity": spec_pos.get("liquidity"),
        },
        "same_range_as_simulation": same_range,
    }
    blocked: list[dict[str, Any]] = []
    available: list[str] = []
    for sid in ("withdrawal_failure", "oracle_failure", "admin_upgrade"):
        r = runs.get(sid)
        if r is None or r.status in ("unsupported", "infra_error", "cancelled", "skipped", "timed_out", "queued"):
            continue
        for s in r.steps or []:
            if not (s["name"].startswith("remove_under_") or s["name"] == "remove_after_upgrade"):
                continue
            cond = s.get("condition")
            if s.get("observed") == "revert":
                if not any(b["condition"] == cond for b in blocked):
                    blocked.append(
                        {
                            "condition": cond,
                            "scenario": sid,
                            "step": s["name"],
                            "revert": (s.get("revert") or {}).get("message"),
                            "tag": "measured",
                            "position_value_unwithdrawable_token1": _frac_to_human(value_token1, pos.dec1),
                            "value_basis": "Removal reverted entirely in the simulation, so the full position value "
                            "(on-chain valuation) is not withdrawable while the condition holds.",
                        }
                    )
            elif cond not in available:
                available.append(cond)
    effects["withdrawal_blocked_under"] = blocked
    effects["withdrawal_succeeded_under"] = available

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
