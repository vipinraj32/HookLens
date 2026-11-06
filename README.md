# HookLens

**See what your liquidity is really exposed to.**

HookLens is an open-source Uniswap v4 tool for liquidity providers and hook developers. You give it
a hook address. It decodes the hook's permissions and runs deterministic static analysis. It then
executes adversarial Foundry scenarios against the hook on a fork, and connects the observed
outcomes to an LP position computed with exact v4 integer math. Every finding links to the evidence
behind it: source lines, bytecode facts, on-chain state, or simulation steps.

> HookLens is **not an audit** and does not certify any hook as safe. It reports what it analysed
> and what it executed, at a pinned block, with the parameters it records. Passing scenarios mean
> those scenarios passed, nothing more.

The original product specification is kept in [docs/product-spec.md](docs/product-spec.md).

## What it does

| Stage | What happens | Where |
|---|---|---|
| Resolve | Validates the address, pins block number and hash, reads runtime code, detects EIP-1967 / EIP-1167 / EIP-897 proxies, fetches verified source (Etherscan v2) or matches local Foundry artifacts (chain 31337), and discovers pools from `PoolManager` `Initialize` logs | `backend/app/services/` |
| Permissions | Decodes the 14 hook permission bits from the address. Constants are generated from the vendored `Hooks.sol`, and a test fails if they drift. The decoded bits are compared with the declared `getHookPermissions()` and with the callbacks actually present in bytecode | `backend/app/analyzers/permissions*.py` |
| Static analysis | Eight analyzer families (PRM, ACC, FEE, ORC, EXT, WDR, ACT, UPG, plus SRC integrity) over the compiler AST and the bytecode. Findings have stable IDs, a deterministic severity with a written rationale, a *confidence basis* (`source-ast`, `bytecode`, `rpc-state`, `simulation`, `metadata`), and evidence references | `backend/app/analyzers/` |
| Adversarial lab | Six env-driven Foundry scenarios (withdrawal failure, oracle failure, fee escalation, admin and upgrade, accounting invariants, transaction ordering) run against the real `PoolManager` and the resolved `PoolKey` on a fork. The planner turns static findings into scenario parameters, and a scenario with nothing to exercise is reported as `unsupported` with a reason | `contracts/test/`, `backend/app/simulation/` |
| LP exposure | Exact-integer port of TickMath, SqrtPriceMath, LiquidityAmounts and FullMath, checked against golden vectors emitted by Forge. Every figure carries a tag: `on-chain`, `measured`, `hypothetical` or `unavailable` | `backend/app/lp/` |
| Evidence | Searchable store of source excerpts with line ranges, bytecode facts, RPC state, simulation steps and decoded traces | `/v1/evidence` |
| AI explanations (optional) | LangGraph flow over Claude. A deterministic validator rejects explanations that cite unknown evidence, cite lines outside that evidence, cite steps that did not run, add numbers, change severity, or claim exploitability or safety | `backend/app/ai/` |
| Reports | Versioned JSON with a content hash, and a PDF (reportlab) | `backend/app/services/report_service.py` |

All long operations (scans, simulations, reports, explanations) run as jobs. Each job has progress
events over SSE (with a polling fallback), cooperative cancellation, timeouts, retries for
retryable infrastructure errors only, and a heartbeat reaper that catches workers that disappear.

## Supported chains

| Chain | ID | Needs |
|---|---|---|
| Ethereum mainnet | 1 | `HOOKLENS_MAINNET_RPC_URL` (archive node for historical blocks and forks). Verified source also needs `HOOKLENS_ETHERSCAN_API_KEY`; without it, mainnet hooks get permission and bytecode analysis only |
| Local Anvil | 31337 | `scripts/dev-chain.sh`, which deploys the HookLens fixture hooks |

RPC endpoints come only from server configuration. Users cannot submit RPC URLs or any other URL
that the server would fetch.

### Fixture hooks

`contracts/src/fixtures/` contains deliberately designed **test fixtures**. They are not real
deployments and not examples of good practice:

`OracleGatedWithdrawalHook`, `DynamicFeeHook`, `PausableAdminHook` (behind an EIP-1967 proxy),
`SwapFeeDeltaHook`, `NoOpHook`, and `MockOracle`.

They give the analyzers and scenarios known, reproducible behaviour to test against. Addresses
land in `contracts/deployments/31337.json`, which is git-ignored.

## Quick start (local development)

Requirements: Git, [Foundry](https://getfoundry.sh) v1.9.0, Python ≥ 3.11 with
[uv](https://docs.astral.sh/uv/), and Node ≥ 22.11 with npm. On Windows, run the shell scripts
from Git Bash.

```bash
git submodule update --init --recursive
(cd contracts && forge build)

# 1. Local chain + fixture hooks (keeps running in the foreground)
scripts/dev-chain.sh

# 2. API on :8000 (SQLite + in-process job runner; migrations run on startup)
cd backend && uv sync && uv run uvicorn app.main:app --port 8000

# 3. Web UI on :3000 (proxies /api/v1/* to the API)
cd frontend && npm ci && npm run dev
```

Open <http://localhost:3000/app/scan>, choose **Local Anvil (HookLens fixtures)**, and paste
`hook_oracle_gated.address` from `contracts/deployments/31337.json`.

From there:
- See the findings and their evidence.
- Open the **Adversarial lab** and run *Withdrawal failure*.
- Compare an LP position on **LP exposure**.
- Generate a report.

For mainnet, copy `.env.example` to `.env` and set `HOOKLENS_MAINNET_RPC_URL` (and optionally
`HOOKLENS_ETHERSCAN_API_KEY` and `HOOKLENS_ANTHROPIC_API_KEY`).

### Docker Compose

```bash
cp .env.example .env    # set HOOKLENS_WORKSPACE_SECRET (>= 32 chars) and POSTGRES_PASSWORD
docker compose up --build                       # mainnet (needs HOOKLENS_MAINNET_RPC_URL)
docker compose --profile dev-chain up --build   # + Anvil with the fixture hooks
```

This runs Postgres, Redis, a migration job, the API, a Celery worker (`default` queue), Celery
beat, a hardened simulation worker (`sim` queue), and the frontend. Only the frontend port is
published. See [docs/deployment.md](docs/deployment.md).

## Tests

| Suite | Command | Notes |
|---|---|---|
| Backend | `cd backend && uv run pytest` | Anvil- and forge-marked tests skip unless a chain with fixtures is running. Set `HL_TEST_ANVIL=1` to make them mandatory |
| Backend lint/types | `uv run ruff check . && uv run ruff format --check . && uv run mypy app` | |
| Contracts | `cd contracts && forge test` | Fixture unit, fuzz and invariant tests, plus LP math vectors. The env-driven scenario entry points skip when run without backend-provided parameters |
| Frontend | `cd frontend && npm run lint && npm run typecheck && npm test` | Vitest + Testing Library |
| End-to-end | `cd frontend && npm run build && npx playwright test` | Needs `scripts/dev-chain.sh` running. Starts the API and the web server itself |

Results on the development machine (Windows 11, Node 22.11, Python 3.12, Foundry 1.9.0) when this
README was written:
- Backend: 107 passed.
- Forge: 20 passed, 6 skipped (the env-driven scenario entry points).
- Vitest: 18 passed.
- Playwright: 2 passed (the desktop workflow and the mobile navigation drawer).

The Docker images and the GitHub Actions workflow have **not** been run yet. See
[FEEDBACK.md](FEEDBACK.md).

## Repository layout

```
backend/    FastAPI app, analyzers, simulation runner, LP math, AI, reports, Alembic migrations
contracts/  Foundry project: fixture hooks, actor harness, scenarios, invariants, deploy script
frontend/   Next.js App Router UI (TypeScript strict, Tailwind v4, TanStack Query, Zod)
docker/     Backend (app + sim targets) and frontend Dockerfiles
docs/       Architecture, threat model, methodology, API, deployment, limitations
scripts/    dev-chain.sh
```

## Documentation

- [Architecture](docs/architecture.md)
- [Threat model](docs/threat-model.md)
- [Analyzers](docs/analyzers.md)
- [Simulation methodology](docs/simulation-methodology.md)
- [LP math](docs/lp-math.md)
- [API](docs/api.md)
- [Deployment](docs/deployment.md)
- [Limitations](docs/limitations.md)
- [Build feedback](FEEDBACK.md)

## License

No license has been chosen yet. Until one is added, the default copyright rules apply.
