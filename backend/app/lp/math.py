"""Exact-integer port of the Uniswap v4-core math used for LP positions.

Ported from v4-core (pinned commit, see permissions_generated.V4_CORE_COMMIT):
  * libraries/TickMath.sol       getSqrtPriceAtTick, getTickAtSqrtPrice
  * libraries/FullMath.sol       mulDiv, mulDivRoundingUp
  * libraries/SqrtPriceMath.sol  getAmount0Delta, getAmount1Delta (rounding flags)
  * test/utils/LiquidityAmounts.sol getLiquidityForAmount{0,1}, getLiquidityForAmounts, getAmountsForLiquidity

Python integers are arbitrary precision, so the Solidity overflow checks are reproduced
explicitly. Results are verified against golden vectors emitted by the Solidity libraries
(contracts/test/unit/LpMathVectors.t.sol).
"""

from __future__ import annotations

MIN_TICK = -887272
MAX_TICK = 887272
MIN_SQRT_PRICE = 4295128739
MAX_SQRT_PRICE = 1461446703485210103287273052203988822378723970342
Q96 = 1 << 96
RESOLUTION = 96
MAX_UINT256 = (1 << 256) - 1
MAX_UINT160 = (1 << 160) - 1
MAX_UINT128 = (1 << 128) - 1


class MathError(ValueError):
    """Raised for inputs the Solidity libraries would revert on."""


def mul_div(a: int, b: int, denominator: int) -> int:
    if denominator == 0:
        raise MathError("mulDiv: division by zero")
    r = (a * b) // denominator
    if r > MAX_UINT256:
        raise MathError("mulDiv: overflow")
    return r


def mul_div_rounding_up(a: int, b: int, denominator: int) -> int:
    r = mul_div(a, b, denominator)
    if (a * b) % denominator:
        if r == MAX_UINT256:
            raise MathError("mulDivRoundingUp: overflow")
        r += 1
    return r


def div_rounding_up(x: int, y: int) -> int:
    return x // y + (1 if x % y else 0)


_TICK_RATIOS = (
    (0x2, 0xFFF97272373D413259A46990580E213A),
    (0x4, 0xFFF2E50F5F656932EF12357CF3C7FDCC),
    (0x8, 0xFFE5CACA7E10E4E61C3624EAA0941CD0),
    (0x10, 0xFFCB9843D60F6159C9DB58835C926644),
    (0x20, 0xFF973B41FA98C081472E6896DFB254C0),
    (0x40, 0xFF2EA16466C96A3843EC78B326B52861),
    (0x80, 0xFE5DEE046A99A2A811C461F1969C3053),
    (0x100, 0xFCBE86C7900A88AEDCFFC83B479AA3A4),
    (0x200, 0xF987A7253AC413176F2B074CF7815E54),
    (0x400, 0xF3392B0822B70005940C7A398E4B70F3),
    (0x800, 0xE7159475A2C29B7443B29C7FA6E889D9),
    (0x1000, 0xD097F3BDFD2022B8845AD8F792AA5825),
    (0x2000, 0xA9F746462D870FDF8A65DC1F90E061E5),
    (0x4000, 0x70D869A156D2A1B890BB3DF62BAF32F7),
    (0x8000, 0x31BE135F97D08FD981231505542FCFA6),
    (0x10000, 0x9AA508B5B7A84E1C677DE54F3E99BC9),
    (0x20000, 0x5D6AF8DEDB81196699C329225EE604),
    (0x40000, 0x2216E584F5FA1EA926041BEDFE98),
    (0x80000, 0x48A170391F7DC42444E8FA2),
)


def get_sqrt_price_at_tick(tick: int) -> int:
    abs_tick = abs(tick)
    if abs_tick > MAX_TICK:
        raise MathError(f"InvalidTick({tick})")
    price = 0xFFFCB933BD6FAD37AA2D162D1A594001 if abs_tick & 0x1 else 1 << 128
    for bit, ratio in _TICK_RATIOS:
        if abs_tick & bit:
            price = (price * ratio) >> 128
    if tick > 0:
        price = MAX_UINT256 // price
    return (price >> 32) + (0 if price % (1 << 32) == 0 else 1)


def get_tick_at_sqrt_price(sqrt_price_x96: int) -> int:
    """Greatest tick whose sqrt price is <= the input (matches TickMath.getTickAtSqrtPrice)."""
    if sqrt_price_x96 < MIN_SQRT_PRICE or sqrt_price_x96 >= MAX_SQRT_PRICE:
        raise MathError(f"InvalidSqrtPrice({sqrt_price_x96})")
    lo, hi = MIN_TICK, MAX_TICK
    while lo < hi:  # binary search over the exact forward function
        mid = (lo + hi + 1) // 2
        if get_sqrt_price_at_tick(mid) <= sqrt_price_x96:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _sort(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def get_amount0_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    if sqrt_a == 0:
        raise MathError("InvalidPrice")
    numerator1 = liquidity << RESOLUTION
    numerator2 = sqrt_b - sqrt_a
    if round_up:
        return div_rounding_up(mul_div_rounding_up(numerator1, numerator2, sqrt_b), sqrt_a)
    return mul_div(numerator1, numerator2, sqrt_b) // sqrt_a


def get_amount1_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    diff = sqrt_b - sqrt_a
    if round_up:
        return mul_div_rounding_up(liquidity, diff, Q96)
    return mul_div(liquidity, diff, Q96)


def _to_uint128(x: int) -> int:
    if x > MAX_UINT128:
        raise MathError("liquidity overflow (uint128)")
    return x


def get_liquidity_for_amount0(sqrt_a: int, sqrt_b: int, amount0: int) -> int:
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    intermediate = mul_div(sqrt_a, sqrt_b, Q96)
    return _to_uint128(mul_div(amount0, intermediate, sqrt_b - sqrt_a))


def get_liquidity_for_amount1(sqrt_a: int, sqrt_b: int, amount1: int) -> int:
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    return _to_uint128(mul_div(amount1, Q96, sqrt_b - sqrt_a))


def get_liquidity_for_amounts(sqrt_price: int, sqrt_a: int, sqrt_b: int, amount0: int, amount1: int) -> int:
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    if sqrt_price <= sqrt_a:
        return get_liquidity_for_amount0(sqrt_a, sqrt_b, amount0)
    if sqrt_price < sqrt_b:
        l0 = get_liquidity_for_amount0(sqrt_price, sqrt_b, amount0)
        l1 = get_liquidity_for_amount1(sqrt_a, sqrt_price, amount1)
        return min(l0, l1)
    return get_liquidity_for_amount1(sqrt_a, sqrt_b, amount1)


def get_amount0_for_liquidity(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    return mul_div(liquidity << RESOLUTION, sqrt_b - sqrt_a, sqrt_b) // sqrt_a


def get_amount1_for_liquidity(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    return mul_div(liquidity, sqrt_b - sqrt_a, Q96)


def get_amounts_for_liquidity(sqrt_price: int, sqrt_a: int, sqrt_b: int, liquidity: int) -> tuple[int, int]:
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    if sqrt_price <= sqrt_a:
        return get_amount0_for_liquidity(sqrt_a, sqrt_b, liquidity), 0
    if sqrt_price < sqrt_b:
        return (
            get_amount0_for_liquidity(sqrt_price, sqrt_b, liquidity),
            get_amount1_for_liquidity(sqrt_a, sqrt_price, liquidity),
        )
    return 0, get_amount1_for_liquidity(sqrt_a, sqrt_b, liquidity)


def mint_amounts(sqrt_price: int, sqrt_a: int, sqrt_b: int, liquidity: int) -> tuple[int, int]:
    """Amounts the PoolManager charges to add `liquidity` (Pool.modifyLiquidity rounds up)."""
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    if sqrt_price < sqrt_a:
        return get_amount0_delta(sqrt_a, sqrt_b, liquidity, True), 0
    if sqrt_price < sqrt_b:
        return get_amount0_delta(sqrt_price, sqrt_b, liquidity, True), get_amount1_delta(
            sqrt_a, sqrt_price, liquidity, True
        )
    return 0, get_amount1_delta(sqrt_a, sqrt_b, liquidity, True)


def burn_amounts(sqrt_price: int, sqrt_a: int, sqrt_b: int, liquidity: int) -> tuple[int, int]:
    """Principal returned when removing `liquidity` (rounded down), excluding fees."""
    sqrt_a, sqrt_b = _sort(sqrt_a, sqrt_b)
    if sqrt_price < sqrt_a:
        return get_amount0_delta(sqrt_a, sqrt_b, liquidity, False), 0
    if sqrt_price < sqrt_b:
        return get_amount0_delta(sqrt_price, sqrt_b, liquidity, False), get_amount1_delta(
            sqrt_a, sqrt_price, liquidity, False
        )
    return 0, get_amount1_delta(sqrt_a, sqrt_b, liquidity, False)


def align_tick(tick: int, spacing: int, *, down: bool = True) -> int:
    if spacing <= 0:
        raise MathError("tick spacing must be positive")
    q = tick // spacing  # floor division (also for negatives)
    aligned = q * spacing
    if not down and aligned != tick:
        aligned += spacing
    return aligned


def usable_tick_bounds(spacing: int) -> tuple[int, int]:
    return align_tick(MIN_TICK, spacing, down=False), align_tick(MAX_TICK, spacing, down=True)
