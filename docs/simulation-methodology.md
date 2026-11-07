# Simulation methodology

Scenarios are ordinary Foundry tests in `contracts/test/scenarios/HookLensScenarios.t.sol`. The
backend configures them through `HL_*` environment variables and runs them on a fork. Every step
records:
- what an LP would expect (`lp_expectation`: `success`, `revert` or none)
- what was observed
- deltas, fees, gas and decoded revert data

The harness writes these steps to JSON (`vm.writeJson`), and the backend parses that file. Tests
do not fail on observed behaviour, so evidence is always produced. `HL_STRICT=true` turns
expectations into assertions.

## Setup on a fork

1. The backend pins a block (`--fork-block-number`). The fork URL is supplied through the
   `hooklens_fork` alias (see the [threat model](threat-model.md)). Chain 31337 forks the local
   Anvil.
2. `HookLensScenarioBase.setUp` reads the real `PoolManager` and the resolved `PoolKey`
   (`HL_POOL_MANAGER`, `HL_CURRENCY0/1`, `HL_FEE`, `HL_TICK_SPACING`, `HL_HOOK`). It deploys v4-core's
   `PoolModifyLiquidityTest` and `PoolSwapTest` routers into the fork.
3. Actor contracts (`LPActor`, `TraderActor`, `UnprivilegedActor` in `src/harness/Actors.sol`) are
   funded with `deal`. Privileged calls use `vm.prank` as the owner detected by static analysis
   (`HL_OWNER`), and only inside the fork. Each one is recorded as a step. Unauthorized probes come
   from `UnprivilegedActor`.
4. Liquidity, swap sizes and the tick range default to small values and can be overridden
   (`HL_LIQUIDITY`, `HL_SWAP_AMOUNT`, `HL_TICK_LOWER/UPPER`).

## Planning

`app/simulation/planner.py` derives each scenario's parameters from the scan. Each scenario's
applicability is decided as follows:

| Scenario | Applies when | Conditions come from |
|---|---|---|
| Withdrawal failure | Always (every LP needs to withdraw) | Detected oracle (revert, zero, negative for Chainlink, stale if a staleness check exists), pause call + owner, and other external call targets |
| Oracle failure | An oracle dependency was detected | The oracle's kind, address and staleness |
| Fee escalation | `BEFORE_SWAP` is enabled, the pool uses a dynamic fee, or fee setters were detected | Detected fee setters and their bounds (probed from both unprivileged and owner accounts) |
| Admin & upgrade | Privileged functions with probe-encodable arguments, or an upgrade selector, were detected | Privileged calls (unauthorized always, authorized when an owner is known), plus the upgrade selector and proxy admin |
| Accounting invariants | Always | n/a |
| Transaction ordering | Always | n/a |

A scenario that does not apply is stored as `unsupported` with the reason, and is not executed.

Adverse conditions are induced with cheatcodes (`vm.mockCallRevert`, `vm.mockCall`, pranked pause or
upgrade calls). They show what happens to an LP **if** the condition occurs. They do not show that
it can occur.

## Outcome statuses

Each step is classified first:

| LP expectation | Observed | Step status |
|---|---|---|
| success | success | `passed` |
| success | revert | `unexpected_revert` |
| revert | revert | `expected_revert` |
| revert | success | `failed` |
| none | revert / success | `observed_revert` / `observed` |

The run status is derived from its steps:

- **`passed`.** Every expectation was met.
- **`unexpected_revert`.** The only violations were unexpected reverts. For example, an LP cannot
  remove liquidity while the oracle reverts.
- **`failed`.** At least one other expectation was violated.
- **`partial`.** No expectation was violated, but a requested condition could not be applied.
- **`inconclusive`.** The test ran but recorded no steps.
- **`infra_error`.** forge could not start, the fork was unavailable, or setup failed before
  results were recorded.
- **`skipped`, `unsupported`, `timed_out`, `cancelled`.** These mean what they say.

**Position awareness (harness ≥ 1.1.0; 1.2.0 adds the accounting and ordering exits).** Every
removal step records `position_liquidity_before`. A removal from an empty position can revert with
`CannotUpdateEmptyPosition()` or, when a non-zero amount is removed, `SafeCastOverflow()`; the metric
covers both. A step
that ran with no position (that metric is 0, or for older runs the PoolManager reverted with
`CannotUpdateEmptyPosition()`) gets step status `not_tested`. It is not a violation and produces no
finding: if the add was rejected (for example `LiquidityNotAllowed()`), withdrawals were simply not
tested. Run details annotate stored steps at read time with `position_check` and
`withdrawal_outcome`. In the accounting scenario a reverted operation (for example a rejected deposit)
moved no balances, so it is reported as `baseline_operation_failed_<step>`, not as an accounting
violation; `accounting_violation_*` is reserved for operations that ran and broke an invariant.

Observed findings with confidence basis `simulation` are derived from violated steps and from
measured fee changes (`app/simulation/interpret.py`).

## Traces and reverts

The backend runs forge with `--json -vvvv`. `traces.py` builds the call tree. `decode.py` decodes
revert data:
- `Error(string)`
- `Panic(uint256)`
- custom errors from local artifacts and known v4 errors
- v4's nested `WrappedError(target, selector, reason, details)`, recursively

The lab UI shows the failing call path and the decoded reason on the final frame.

## Reproducibility

Each run stores the following, which is enough to reproduce it:
- the full `SimulationSpec`: chain, block number and hash, hook and implementation code hashes,
  `PoolKey`, scenario env and harness version
- a copy-pasteable command that uses `--fork-url hooklens_fork`

The command does not contain the RPC URL. Re-running it needs `HOOKLENS_FORK_RPC_URL` set locally.

## Local verification

The env-driven entry points skip under a plain `forge test`, which is why 6 tests are skipped.
They are exercised by:
- `test/unit/FixtureScenarios.t.sol`, which runs the same scenario logic against locally deployed
  fixtures
- the backend integration tests (`pytest -m "anvil or forge"`)
- the Playwright workflow
