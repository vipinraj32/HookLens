"""The Python LP math must match the Solidity libraries bit for bit (golden vectors from forge)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.errors import AppError
from app.lp import math as m
from app.lp.position import build_position, parse_amount, raw_price

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "lp_math_vectors.json").read_text())["vectors"]


def test_vector_count() -> None:
    assert len(VECTORS) >= 50


@pytest.mark.parametrize("v", [v for v in VECTORS if v["kind"] == "tick"], ids=lambda v: f"tick{v['tick']}")
def test_tick_vectors(v: dict) -> None:
    sp = m.get_sqrt_price_at_tick(v["tick"])
    assert str(sp) == v["sqrt_price_x96"]
    if sp < m.MAX_SQRT_PRICE:
        assert m.get_tick_at_sqrt_price(sp) == v["tick_at_sqrt"]


@pytest.mark.parametrize("v", [v for v in VECTORS if v["kind"] == "sqrt"], ids=lambda v: v["sqrt_price_x96"][:12])
def test_sqrt_vectors(v: dict) -> None:
    assert m.get_tick_at_sqrt_price(int(v["sqrt_price_x96"])) == v["tick"]


@pytest.mark.parametrize(
    "v",
    [v for v in VECTORS if v["kind"] == "position"],
    ids=lambda v: f"{v['tick_lower']}_{v['tick_upper']}_{v['tick']}",
)
def test_position_vectors(v: dict) -> None:
    sp, sa, sb = (m.get_sqrt_price_at_tick(v[k]) for k in ("tick", "tick_lower", "tick_upper"))
    liq = m.get_liquidity_for_amounts(sp, sa, sb, int(v["amount0_in"]), int(v["amount1_in"]))
    assert str(liq) == v["liquidity"]
    a0, a1 = m.get_amounts_for_liquidity(sp, sa, sb, liq)
    assert (str(a0), str(a1)) == (v["amount0_for_liquidity"], v["amount1_for_liquidity"])
    r0, r1 = m.mint_amounts(sp, sa, sb, liq)
    assert (str(r0), str(r1)) == (v["amount0_mint_round_up"], v["amount1_mint_round_up"])


def test_bounds_and_errors() -> None:
    assert m.get_sqrt_price_at_tick(m.MIN_TICK) == m.MIN_SQRT_PRICE
    assert m.get_sqrt_price_at_tick(m.MAX_TICK) == m.MAX_SQRT_PRICE
    with pytest.raises(m.MathError):
        m.get_sqrt_price_at_tick(m.MAX_TICK + 1)
    with pytest.raises(m.MathError):
        m.get_tick_at_sqrt_price(m.MAX_SQRT_PRICE)
    with pytest.raises(m.MathError):
        m.mul_div(1, 1, 0)


def test_rounding_direction_never_favours_lp() -> None:
    sp, sa, sb = m.get_sqrt_price_at_tick(10), m.get_sqrt_price_at_tick(-600), m.get_sqrt_price_at_tick(600)
    for liq in (1, 7, 10**6 + 3, 10**18 + 11):
        mint = m.mint_amounts(sp, sa, sb, liq)
        burn = m.burn_amounts(sp, sa, sb, liq)
        assert mint[0] >= burn[0] and mint[1] >= burn[1]


def test_align_tick_negative_floor() -> None:
    assert m.align_tick(-1, 60) == -60
    assert m.align_tick(-60, 60) == -60
    assert m.align_tick(-1, 60, down=False) == 0
    assert m.usable_tick_bounds(60) == (-887220, 887220)


def _pool_state(tick: int) -> dict:
    return {
        "initialized": True,
        "sqrt_price_x96": str(m.get_sqrt_price_at_tick(tick)),
        "tick": tick,
        "liquidity": str(10**20),
    }


def test_build_position_in_range_and_price_bounds() -> None:
    pos, notes = build_position(
        pool_state=_pool_state(0),
        tick_spacing=60,
        dec0=18,
        dec1=18,
        tick_lower=None,
        tick_upper=None,
        price_lower="0.9",
        price_upper="1.1",
        amount0=10**18,
        amount1=10**18,
        liquidity=None,
    )
    assert pos.tick_lower % 60 == 0 and pos.tick_upper % 60 == 0
    assert pos.tick_lower < 0 < pos.tick_upper
    assert pos.range_state() == "in-range"
    a0, a1 = pos.deposit()
    assert a0 <= 10**18 and a1 <= 10**18 and max(a0, a1) > 10**18 * 99 // 100
    assert len(notes) == 2


def test_build_position_rejects_bad_input() -> None:
    with pytest.raises(AppError):
        build_position(
            pool_state=_pool_state(0),
            tick_spacing=60,
            dec0=18,
            dec1=18,
            tick_lower=61,
            tick_upper=120,
            price_lower=None,
            price_upper=None,
            amount0=1,
            amount1=1,
            liquidity=None,
        )
    with pytest.raises(AppError):  # range above price with only token1 -> zero liquidity
        build_position(
            pool_state=_pool_state(0),
            tick_spacing=60,
            dec0=18,
            dec1=18,
            tick_lower=600,
            tick_upper=1200,
            price_lower=None,
            price_upper=None,
            amount0=0,
            amount1=10**18,
            liquidity=None,
        )
    with pytest.raises(AppError):
        build_position(
            pool_state={"initialized": False},
            tick_spacing=60,
            dec0=18,
            dec1=18,
            tick_lower=-60,
            tick_upper=60,
            price_lower=None,
            price_upper=None,
            amount0=1,
            amount1=1,
            liquidity=None,
        )


def test_parse_amount_and_price() -> None:
    assert parse_amount("1.5", 6, "a") == 1_500_000
    assert parse_amount("0.0000001", 6, "a") == 0
    with pytest.raises(AppError):
        parse_amount("1", None, "a")
    assert raw_price(m.Q96) == 1
    assert Decimal(1) == Decimal(raw_price(m.Q96).numerator)
