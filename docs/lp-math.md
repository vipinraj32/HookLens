# LP math

`backend/app/lp/math.py` is an exact port of the v4-core libraries to Python integers. It never
uses floating point, and it keeps v4's rounding directions.

| Library | Functions |
|---|---|
| FullMath | `mul_div`, `mul_div_rounding_up` |
| UnsafeMath | `div_rounding_up` |
| TickMath | `get_sqrt_price_at_tick`, `get_tick_at_sqrt_price`, `MIN/MAX_TICK`, `MIN/MAX_SQRT_PRICE` |
| SqrtPriceMath | `get_amount0_delta`, `get_amount1_delta` (signed, with round-up on mint and round-down on burn) |
| LiquidityAmounts (periphery) | `get_liquidity_for_amount0/1`, `get_liquidity_for_amounts`, `get_amount0/1_for_liquidity`, `get_amounts_for_liquidity` |
| Helpers | `mint_amounts` and `burn_amounts` (what the PoolManager charges or pays), `align_tick`, `usable_tick_bounds` |

## Verification against Solidity

`contracts/test/unit/LpMathVectors.t.sol` runs the real v4-core libraries. It writes 51 golden
vectors (ticks, sqrt prices, liquidity and amounts, including the boundary ticks) to
`backend/tests/fixtures/lp_math_vectors.json`. `backend/tests/test_lp_math.py` asserts that the
Python port reproduces every vector exactly. When the vendored v4-core changes, regenerate the
vectors with `forge test --match-contract LpMathVectors`.

## Positions (`lp/position.py`)

- **Inputs.** A range given as ticks or as human prices (converted with the tokens' decimals),
  plus either raw token amounts or a liquidity value. Ticks are aligned to the pool's tick
  spacing, and inverted ranges are rejected. The API also rejects an uninitialized pool, amounts
  that produce zero liquidity, and liquidity above uint128.
- **Liquidity and amounts.** When amounts are given, liquidity is derived with
  `get_liquidity_for_amounts` at the pool's current `sqrtPriceX96`, which is read on chain at the
  pinned block. Deposit amounts use the rounding-up mint path.
  - For an in-range position with only one amount, liquidity is sized from that token alone
    (`get_liquidity_for_amount0` over `[price, upper)`, or `get_liquidity_for_amount1` over
    `[lower, price)`). The deposit then shows how much of the other token is needed. With both
    amounts, the scarcer side decides (the standard `min`).
  - An out-of-range position with only the token it cannot hold is rejected with
    `wrong_token_for_range`, and the message names the token the range needs.
- **Range state.** `below-range` (all token0), `in-range` or `above-range` (all token1), from the
  current tick.
- **Display values.** Human-readable values are produced with `Decimal` from exact `Fraction`s at
  the token's decimals, and are kept as strings end-to-end. The UI groups digits without
  converting them to floats.

## Valuation (`lp/valuation.py`)

Every number is returned as `{value, tag, basis}`:

| Tag | Meaning |
|---|---|
| `live` | Pool state read at the chain's latest block when the comparison ran (default) |
| `historical` | Pool state from the scan snapshot at its pinned block (`state_source: "scan"`) |
| `measured` | Taken from an executed simulation run, at that run's fork block |
| `hypothetical` | Depends on an assumption that is stated next to it |
| `unavailable` | Cannot be computed honestly from the data available. The reason is given |

### Baseline

Pool facts (price, tick, active liquidity) carry the `live` or `historical` tag of their source.
The position itself is a model built from your inputs and is tagged `hypothetical`: its deposits,
value, range state, and the share of active liquidity it *would* hold if added. It is not an
existing on-chain position. Live state is read through `app/services/live_pool.py`: chain id is
verified, the head is cached for `HOOKLENS_LIVE_HEAD_TTL_S` seconds, state is cached per block, and
concurrent reads of the same block share one RPC round trip. An RPC failure is an error; the scan
snapshot is never substituted silently.

### Price scenarios (hypothetical)

- The default moves are −50%, −20%, −10%, 0, +10%, +20% and +50%. Callers may pass up to 21 moves
  in the range (−100%, +10 000%].
- For a move `m` the price is multiplied by `1+m`, so `sqrtPrice` is multiplied by `√(1+m)` and
  clamped to the TickMath bounds.
- For each move, HookLens computes:
  - **LP value**: the position's token amounts at the new price, valued in token1.
  - **Hold value**: the originally deposited amounts, valued at the new price.
  - **Divergence**: LP value minus hold value, as an absolute amount and as a percentage.
- Fees are **excluded**, and each row's assumption string says so. HookLens has no fee forecast.

### Simulation effects (measured)

These come from a selected simulation:

- **Position creation.** `created`, `rejected` (with the revert) or `not_attempted`, from the
  scenario's first add.
- **Withdrawal outcome.** `withdrawal.status` is `completed`, `blocked`, `not_tested`,
  `unsupported` or `execution_error`, taken from the withdrawal, oracle and upgrade scenarios. A
  removal counts as blocked only when the harness held a position (`position_liquidity_before > 0`,
  harness ≥ 1.1.0) and the removal reverted. Removals that reverted with
  `CannotUpdateEmptyPosition()` because no position was ever created are listed under
  `withdrawal_not_tested`, never as blocked. `recover_after_*` successes are listed under
  `withdrawal_recovered_after`, not as success under the condition.
- **Block references.** `fork_block`, `state_block` and `blocks_since_simulation` keep the
  historical run separate from the state above it. Stored simulation results are never rewritten.
- **Fees.** The LP fee observed in the fork's `Swap` events: the baseline, and the maximum after an
  owner-initiated change.
- **Range comparison.** Whether the simulated position used the same range as the user's
  (`same_range_as_simulation`). Measured outcomes can depend on the range and on the position
  size, so the UI shows this flag next to the measured results.

If there is no simulation, or a scenario did not run, the result is `unavailable` with a reason.
