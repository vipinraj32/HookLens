# Threat model

HookLens executes and analyses contracts chosen by anonymous users. It also holds server-side
secrets: RPC URLs that may embed API keys, an Etherscan key and an Anthropic key. This document
covers what is defended, how, and what is **not** defended yet.

## Assets

- Server secrets: `HOOKLENS_MAINNET_RPC_URL`, `HOOKLENS_ETHERSCAN_API_KEY`,
  `HOOKLENS_ANTHROPIC_API_KEY` and `HOOKLENS_WORKSPACE_SECRET`.
- Integrity of results: findings, simulation outcomes and reports must reflect what actually ran.
- Availability of workers and RPC quota.

HookLens holds **no private keys**:
- It never asks for a wallet, a seed phrase or a private key, and analysis never requires a
  wallet.
- The only key in the repository is Anvil's well-known public development key. The fixture deploy
  uses it, and only against chain 31337.

## Controls

| Threat | Control | Code |
|---|---|---|
| SSRF through user-supplied URLs | No input accepts a URL. Chains and RPC endpoints are a fixed server-side registry, and users pick a `chain_id` | `app/chains.py`, `app/api/schemas.py` |
| Secret leakage in argv | The fork URL is passed through the `HOOKLENS_FORK_RPC_URL` env var and referenced via the `hooklens_fork` alias in `foundry.toml`, never on the command line. Repro commands stored in results reference the alias | `app/simulation/forge_runner.py` |
| Secret leakage in logs or responses | Secrets are `SecretStr`. JSON logs pass through `redact()` (API-key params, key-in-path RPC URLs, `sk-ant-…`, bearer tokens). Errors are returned as problem+json without internals | `app/observability.py`, `app/errors.py` |
| Code execution through Foundry | `forge` is called with an argument list (no shell) and a fixed binary. FFI is forced off. The env is an allowlist (OS essentials + `HL_*` + the fork URL). `fs_permissions` limits writes to `contracts/sim-out` and `contracts/deployments`. There are per-scenario wall-clock timeouts, and cancellation kills the process | `forge_runner.py`, `contracts/foundry.toml` |
| Untrusted contract *source* | Users never upload Solidity. Only Etherscan-verified source or the repo's own artifacts are compiled, and the scenario harness is fixed repo code | `app/services/sources.py` |
| Abuse / resource exhaustion | Per-client rate limits (requests and job creation). Bounded inputs (address length, `price_moves` ≤ 21 values in (−100%, +10 000%]). Bounded log scans (`log_scan_max_chunks`). Job timeouts | `app/api/security.py`, `app/api/routes_lp.py`, `app/config.py` |
| Cross-workspace access | Records are scoped to an HMAC-signed workspace ID. An invalid `X-HookLens-Workspace` header gets a 401. An invalid cookie gets replaced by a fresh workspace with no records | `app/api/security.py` |
| Weak production configuration | Settings refuse to start with `environment=production` if the workspace secret is the dev default or shorter than 32 characters | `app/config.py` |
| AI fabricating claims | The deterministic validator rejects unknown evidence IDs, out-of-range lines, steps that didn't run, novel numbers, changed severity, and exploitability or safety claims. After two failed attempts the explanation is stored as `rejected`, not shown as valid | `app/ai/validator.py`, `app/ai/graph.py` |
| Container breakout impact | Containers run as non-root (uid 10001) with `cap_drop: ALL` and `no-new-privileges`. The sim-worker additionally has PID, memory and CPU limits, `/tmp` on tmpfs, and FFI disabled. Postgres, Redis and Anvil sit on an `internal: true` network | `docker-compose.yml`, `docker/backend.Dockerfile` |

## Known gaps (not yet defended)

- **Sim-worker egress is not restricted by hostname.** The worker needs egress to the RPC provider
  for mainnet forks, and Compose cannot express "only this host". A hook's code cannot open network
  connections itself (the EVM has no network access and FFI is off), but a compromised `forge`
  process could. In production, use an egress proxy or a network policy that allows only the RPC
  host.
- **The sim-worker root filesystem is not read-only.** Foundry writes its cache and outputs in the
  project directory. Only `/tmp` is tmpfs.
- **Local (non-Docker) runs only have process-level isolation.** On a developer machine, `forge`
  runs as the developer's user.
- **Rate limiting is per process** (fixed window, in memory). With several API replicas, enforce
  limits at a proxy.
- **No Content-Security-Policy** is set yet. The frontend sends `X-Frame-Options: DENY`,
  `Referrer-Policy` and `X-Content-Type-Options`.
- **Workspaces are not accounts.** Anyone holding the cookie value has that workspace's records.
  Results are not confidential: they describe public on-chain contracts.
- **Cheatcodes in scenarios.** Conditions (oracle failure, pause, impersonated owner) are induced
  with `vm.mockCall`, `vm.prank` and `deal` on a local fork. This is intended and recorded in every
  result, but it means a scenario shows what *would* happen under the condition, not that the
  condition can occur on chain.
