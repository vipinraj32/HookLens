# Limitations

HookLens reports what it analysed and executed. It does not certify safety. Specifically:

## Analysis

- Static analysis covers verified or locally matched source only. A bytecode-only hook gets
  permission, selector and opcode checks, and anything deeper is reported as `unknown`.
- Contracts the hook calls (oracles, vaults, routers) are recorded as dependencies but not
  analysed.
- There is no symbolic execution, and no third-party analyzer (such as Slither) is integrated.
- Pool discovery scans `PoolManager` `Initialize` logs in bounded chunks. On mainnet, the scan starts at
  the PoolManager deployment block and covers at most
  `log_scan_max_chunks × log_scan_chunk_blocks` blocks (6,000,000 by default). Pools created later
  are not found unless a `pool_id` is given. When the RPC rejects log ranges (free-plan caps), discovery uses
  Etherscan's log API instead (needs `HOOKLENS_ETHERSCAN_API_KEY`; capped at 300 requests).

## Simulation

- Each run covers one pool at one pinned block, with the recorded parameters. Other states, sizes
  and ranges can behave differently.
- Adverse conditions are induced with cheatcodes (`mockCall`, `prank`, `deal`). A scenario shows
  the effect **if** a condition occurs, not that it can occur on chain.
- Scenario inputs come from static analysis. If the analyzers miss a dependency, no scenario
  exercises it.
- Fee probes and admin calls only use argument types the planner can encode. Other calls are
  listed as not probed.
- Mainnet forks need `HOOKLENS_MAINNET_RPC_URL` (an archive node for past blocks). Without it,
  mainnet simulations are unavailable.

## LP figures

- Price scenarios are instantaneous and hypothetical, and they exclude fees.
- Measured effects come from the simulated position, and its range may differ from the user's.
  The UI flags this.
- There is no fee or APR forecasting.

## AI

- Explanations are optional and need `HOOKLENS_ANTHROPIC_API_KEY`.
- The validator checks references and numbers against the provided evidence. It cannot prove that
  the prose is a correct interpretation. Explanations are shown with the model that generated them, and they
  never change severity.

## Platform

- On local Windows or macOS runs, `forge` only has process-level isolation.
- There are no user accounts: workspaces are anonymous cookies.
- Only Ethereum mainnet, Sepolia and local Anvil are supported.
- The Docker images were not built on the development machine (see [deployment](deployment.md)).
