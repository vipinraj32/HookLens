"""LP position modelling on top of the exact v4 math.

Prices are expressed as "token1 per token0" in human units unless stated as raw. Raw prices
are exact rationals (sqrtPriceX96^2 / 2^192); human prices are rendered with Decimal at 50
significant digits for display only — every amount is computed from integers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation, getcontext
from fractions import Fraction
from typing import Any

from app.errors import AppError
from app.lp import math as lpm

getcontext().prec = 80
CALCULATION_VERSION = "hooklens-lp/1.0.0"


def raw_price(sqrt_price_x96: int) -> Fraction:
    """token1 raw units per token0 raw unit."""
    return Fraction(sqrt_price_x96 * sqrt_price_x96, 1 << 192)


def human_price(sqrt_price_x96: int, dec0: int, dec1: int) -> Decimal:
    p = raw_price(sqrt_price_x96) * Fraction(10**dec0, 10**dec1)
    return Decimal(p.numerator) / Decimal(p.denominator)


def fmt_decimal(d: Decimal, places: int = 18) -> str:
    q = Decimal(1).scaleb(-places)
    s = format(d.quantize(q, rounding=ROUND_DOWN) if d.adjusted() < 40 else d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def to_human(raw: int, decimals: int) -> str:
    return fmt_decimal(Decimal(raw).scaleb(-decimals), decimals)


def parse_amount(value: str | None, decimals: int | None, field: str) -> int | None:
    """Human decimal string -> raw integer units (truncates beyond the token's precision)."""
    if value in (None, ""):
        return None
    if decimals is None:
        raise AppError("decimals_unknown", f"Token decimals are unknown; provide {field}_raw instead.", status_code=422)
    try:
        d = Decimal(str(value))
    except InvalidOperation as e:
        raise AppError("invalid_amount", f"{field} is not a decimal number.", status_code=422) from e
    if d < 0:
        raise AppError("invalid_amount", f"{field} must be non-negative.", status_code=422)
    raw = int((d * (Decimal(10) ** decimals)).to_integral_value(rounding=ROUND_DOWN))
    if raw.bit_length() > 255:
        raise AppError("invalid_amount", f"{field} is too large.", status_code=422)
    return raw


def sqrt_price_from_human(price: Decimal, dec0: int, dec1: int) -> int:
    if price <= 0:
        raise AppError("invalid_price", "Prices must be positive.", status_code=422)
    raw = price * Decimal(10**dec1) / Decimal(10**dec0)
    sp = int((raw.sqrt() * Decimal(2**96)).to_integral_value(rounding=ROUND_DOWN))
    return min(max(sp, lpm.MIN_SQRT_PRICE), lpm.MAX_SQRT_PRICE - 1)


def tick_for_price(price: Decimal, dec0: int, dec1: int, spacing: int, *, up: bool) -> int:
    tick = lpm.get_tick_at_sqrt_price(sqrt_price_from_human(price, dec0, dec1))
    return lpm.align_tick(tick, spacing, down=not up)


@dataclass
class Position:
    tick_lower: int
    tick_upper: int
    liquidity: int
    sqrt_price_x96: int
    current_tick: int
    dec0: int
    dec1: int

    @property
    def sqrt_lower(self) -> int:
        return lpm.get_sqrt_price_at_tick(self.tick_lower)

    @property
    def sqrt_upper(self) -> int:
        return lpm.get_sqrt_price_at_tick(self.tick_upper)

    def range_state(self, tick: int | None = None) -> str:
        t = self.current_tick if tick is None else tick
        if t < self.tick_lower:
            return "below-range"  # all token0
        if t >= self.tick_upper:
            return "above-range"  # all token1
        return "in-range"

    def amounts_at(self, sqrt_price: int) -> tuple[int, int]:
        return lpm.get_amounts_for_liquidity(sqrt_price, self.sqrt_lower, self.sqrt_upper, self.liquidity)

    def deposit(self) -> tuple[int, int]:
        return lpm.mint_amounts(self.sqrt_price_x96, self.sqrt_lower, self.sqrt_upper, self.liquidity)

    def value_in_token1(self, amount0: int, amount1: int, sqrt_price: int) -> Fraction:
        return amount0 * raw_price(sqrt_price) + amount1


def build_position(
    *,
    pool_state: dict[str, Any],
    tick_spacing: int,
    dec0: int | None,
    dec1: int | None,
    tick_lower: int | None,
    tick_upper: int | None,
    price_lower: str | None,
    price_upper: str | None,
    amount0: int | None,
    amount1: int | None,
    liquidity: int | None,
    sym0: str = "token0",
    sym1: str = "token1",
) -> tuple[Position, list[str]]:
    notes: list[str] = []
    if not pool_state or not pool_state.get("initialized"):
        raise AppError("pool_not_initialized", "The pool is not initialized at the pinned block.", status_code=422)
    if dec0 is None or dec1 is None:
        raise AppError(
            "decimals_unknown",
            "Token decimals could not be read, so prices cannot be expressed in token units.",
            status_code=422,
        )
    sp = int(pool_state["sqrt_price_x96"])
    tick = int(pool_state["tick"])
    lo_ok, hi_ok = lpm.usable_tick_bounds(tick_spacing)
    if tick_lower is None and price_lower is not None:
        tick_lower = tick_for_price(Decimal(price_lower), dec0, dec1, tick_spacing, up=False)
        notes.append(f"price_lower {price_lower} -> tick {tick_lower} (aligned down to spacing {tick_spacing})")
    if tick_upper is None and price_upper is not None:
        tick_upper = tick_for_price(Decimal(price_upper), dec0, dec1, tick_spacing, up=True)
        notes.append(f"price_upper {price_upper} -> tick {tick_upper} (aligned up to spacing {tick_spacing})")
    if tick_lower is None or tick_upper is None:
        raise AppError("range_required", "Provide tick_lower/tick_upper or price_lower/price_upper.", status_code=422)
    if tick_lower % tick_spacing or tick_upper % tick_spacing:
        raise AppError(
            "invalid_ticks", f"Ticks must be multiples of the pool tick spacing ({tick_spacing}).", status_code=422
        )
    if tick_lower < lo_ok or tick_upper > hi_ok:
        raise AppError("invalid_ticks", f"Ticks must be within the usable range [{lo_ok}, {hi_ok}].", status_code=422)
    if tick_lower >= tick_upper:
        raise AppError("invalid_ticks", "tick_lower must be below tick_upper.", status_code=422)
    sa, sb = lpm.get_sqrt_price_at_tick(tick_lower), lpm.get_sqrt_price_at_tick(tick_upper)
    if liquidity is None:
        if not amount0 and not amount1:
            raise AppError("amount_required", "Provide token amounts or liquidity.", status_code=422)
        if sp <= sa and not amount0:
            raise AppError(
                "wrong_token_for_range",
                f"The range is entirely above the current price, so the position holds only {sym0}. "
                f"Provide a {sym0} amount.",
                status_code=422,
            )
        if sp >= sb and not amount1:
            raise AppError(
                "wrong_token_for_range",
                f"The range is entirely below the current price, so the position holds only {sym1}. "
                f"Provide a {sym1} amount.",
                status_code=422,
            )
        in_range = sa < sp < sb
        if in_range and amount0 and not amount1:
            # One-sided input for an in-range position: size from token0; token1 needed follows from the math.
            liquidity = lpm.get_liquidity_for_amount0(sp, sb, amount0)
            notes.append(f"Only {sym0} was given: liquidity is sized from it; the {sym1} it needs is in the deposit.")
        elif in_range and amount1 and not amount0:
            liquidity = lpm.get_liquidity_for_amount1(sa, sp, amount1)
            notes.append(f"Only {sym1} was given: liquidity is sized from it; the {sym0} it needs is in the deposit.")
        else:
            liquidity = lpm.get_liquidity_for_amounts(sp, sa, sb, amount0 or 0, amount1 or 0)
    if liquidity <= 0:
        raise AppError(
            "zero_liquidity",
            "These amounts are too small to produce any liquidity for this range.",
            status_code=422,
        )
    if liquidity > lpm.MAX_UINT128:
        raise AppError("liquidity_overflow", "Liquidity exceeds uint128.", status_code=422)
    return Position(tick_lower, tick_upper, liquidity, sp, tick, dec0, dec1), notes
