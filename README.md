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
| Permissions | Decodes the 14 hook permission bits from the address. Constants are generated from the vendored `Hooks.sol`, and a test fails if they drift. The decoded bits are compared with the declared `getHookPermissions()` and with the callbacks actually present in bytecode | `packages/hooklens/src/hooklens/analyzers/permissions*.py` |
| Static analysis | Eight analyzer families (PRM, ACC, FEE, ORC, EXT, WDR, ACT, UPG, plus SRC integrity) over the compiler AST and the bytecode. Findings have stable IDs, a deterministic severity with a written rationale, a *confidence basis* (`source-ast`, `bytecode`, `rpc-state`, `simulation`, `metadata`), and evidence references | `packages/hooklens/src/hooklens/analyzers/` (shared by the web app and the CLI) |
| Adversarial lab | Six env-driven Foundry scenarios (withdrawal failure, oracle failure, fee escalation, admin and upgrade, accounting invariants, transaction ordering) run against the real `PoolManager` and the resolved `PoolKey` on a fork. The planner turns static findings into scenario parameters, and a scenario with nothing to exercise is reported as `unsupported` with a reason | `contracts/test/`, `backend/app/simulation/` |
| LP exposure | Exact-integer port of TickMath, SqrtPriceMath, LiquidityAmounts and FullMath, checked against golden vectors emitted by Forge. Every figure carries a tag: `on-chain`, `measured`, `hypothetical` or `unavailable` | `backend/app/lp/` |
| Evidence | Searchable store of source excerpts with line ranges, bytecode facts, RPC state, simulation steps and decoded traces | `/v1/evidence` |
| AI explanations (optional) | LangGraph flow over Claude. A deterministic validator rejects explanations that cite unknown evidence, cite lines outside that evidence, cite steps that did not run, add numbers, change severity, or claim exploitability or safety | `backend/app/ai/` |
| Reports | Versioned JSON with a content hash, and a PDF (reportlab) | `backend/app/services/report_service.py` |

All long operations (scans, simulations, reports, explanations) run as jobs. Each job has progress
events over SSE (with a polling fallback), cooperative cancellation, timeouts, retries for
retryable infrastructure errors only, and a heartbeat reaper that catches workers that disappear.

## Command-line scanner and GitHub Action

The analyzers are also packaged as a local-first CLI, `hooklens`. It scans Solidity source in a
local project or a public GitHub repository. Static scans need no API key, database, server,
Foundry or RPC endpoint; at most, a `solc` binary is downloaded. It uses the same analysis engine
as the web app.

### Install

```bash
pip install "hooklens @ git+https://github.com/vipinraj32/HookLens#subdirectory=packages/hooklens"
hooklens --help
```

> The PyPI name `hooklens` belongs to an **unrelated project**, so `pip install hooklens` installs
> the wrong package. Install from Git as shown, from a checkout (`pip install ./packages/hooklens`),
> or from a release wheel.

### Use it

```bash
# A local Foundry/Hardhat project (or a subdirectory of one)
hooklens scan ./my-hook-project --local --html report.html

# A public GitHub repository: cloned into a temp dir, nothing in it is executed, then deleted
hooklens scan https://github.com/uniswapfoundation/v4-template --html report.html

# CI style: machine-readable reports and a severity gate
hooklens scan . --json report.json --sarif report.sarif --fail-on high

hooklens init --github-action   # writes hooklens.toml and .github/workflows/hooklens.yml
hooklens rules                  # lists every rule id
hooklens scan . -v              # also prints informational findings
```

Open `report.html` in a browser. It is a single file and works offline.

**In GitHub Actions**, use the composite action at the root of this repository:

```yaml
permissions:
  contents: read
  security-events: write
jobs:
  hooklens:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { submodules: recursive }
      - uses: vipinraj32/HookLens@main   # pin a tag or commit SHA once one is published
        with:
          fail-on: high
          comment-on-pr: false
```

Each run produces:
- a job summary;
- findings in **Security → Code scanning** (SARIF);
- the HTML, JSON and SARIF reports as an artifact;
- optionally, a single PR comment that is updated on every run.

For pull requests from forks, the SARIF upload and the PR comment are skipped automatically. A
full example is in [examples/github-actions/hooklens.yml](examples/github-actions/hooklens.yml).

**Execution testing.** `hooklens lab --chain 31337 --hook 0x… --json lab.json` runs the
Foundry/Anvil scenarios (withdrawal failure, oracle failure, fee escalation, admin and upgrade,
accounting, ordering) against a *deployed* hook. It goes through a running HookLens server with
`forge` and an RPC endpoint. Results are per-scenario run statuses for one fork at one block.

### What it tells you

**Contracts.** Each compiled contract is classified as `hook`, `candidate`, `abstract-hook`,
`mock`, `interface`, `library` or `not-a-hook`, with a confidence level and the reasons. The
callbacks it implements are listed too. Only hooks and candidates are analysed by default.

**Findings.** Each finding has:

| Field | Example |
|---|---|
| Stable id and rule | `HL-…`, `HL.WDR.withdrawal_revert_conditions` |
| Severity | critical / high / medium / low / informational (deterministic, rule-based) |
| Location | `src/MyHook.sol:57`, contract and function |
| Description | "1 revert condition(s) reachable from beforeRemoveLiquidity: `block.timestamp < unlockTime`" |
| Evidence | The source excerpt and line range that triggered it |
| LP implications and mitigations | What it can mean for liquidity providers, and what to check |
| Confidence and basis | How certain the rule is, and what it rests on (e.g. `source-ast`) |

The checks cover:
- **Withdrawal** blockers (pauses, locks, conditions that revert liquidity removal).
- **Oracle** dependence, and whether the oracle address can be replaced.
- **Dynamic fees** controlled by the hook.
- **Access control**: privileged state used inside callbacks, `tx.origin`.
- **Upgradeability**: proxies, upgrade functions, unguarded initializers.
- **External calls** made from callbacks.
- **Custom accounting** and return-delta permissions.
- **Permission problems**: invalid sets, or callbacks that are declared but not implemented.

**Scan details.** The scan status (`completed`, `partial`, `failed` or `no-hooks`), the compiler
version and settings, skipped files, and a scope-and-limitations statement.

**Exit codes**:

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Findings at or above `--fail-on` |
| 2 | Config or usage error |
| 3 | Source error (path or repository) |
| 4 | Analysis error (imports, compiler, partial scan) |
| 5 | Report error |

A scanner error is never reported as a security result, and vice versa.

> Findings are **static indicators that need review, not confirmed exploits**. A report with no
> findings does **not** mean a hook is safe. A static scan reads source at one commit. It does not
> know the deployed address, the on-chain owner or the oracle state, and it executes nothing.

See [docs/cli.md](docs/cli.md) for configuration (`hooklens.toml`), every option, report formats
and methodology.

## Supported chains

| Chain | ID | Needs |
|---|---|---|
| Ethereum mainnet | 1 | `HOOKLENS_MAINNET_RPC_URL` (archive node for historical blocks and forks). Verified source also needs `HOOKLENS_ETHERSCAN_API_KEY`; without it, mainnet hooks get permission and bytecode analysis only |
| Sepolia testnet | 11155111 | `HOOKLENS_SEPOLIA_RPC_URL`. Pool discovery scans logs back to block 7,258,946 (PoolManager deployment); when the RPC plan caps `eth_getLogs` ranges (Alchemy free: 10 blocks), it falls back to Etherscan's log API if `HOOKLENS_ETHERSCAN_API_KEY` is set. The same key enables verified source |
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

For mainnet or Sepolia, copy `.env.example` to `.env` and set `HOOKLENS_MAINNET_RPC_URL` and/or
`HOOKLENS_SEPOLIA_RPC_URL` (and optionally
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
| CLI package | `cd packages/hooklens && uv sync && uv run pytest` | Fixture hooks, reports (JSON schema, SARIF, HTML escaping/CSP), CLI exit codes, config, import resolution, GitHub acquisition (mocked), `lab` (mocked API), and the composite action's scripts. `HOOKLENS_TEST_NETWORK=1 uv run pytest -m network` clones and scans uniswapfoundation/v4-template |
| CLI lint/types/build | `uv run ruff check src tests && uv run mypy src && uv build` | |
| Contracts | `cd contracts && forge test` | Fixture unit, fuzz and invariant tests, plus LP math vectors. The env-driven scenario entry points skip when run without backend-provided parameters |
| Frontend | `cd frontend && npm run lint && npm run typecheck && npm test` | Vitest + Testing Library |
| End-to-end | `cd frontend && npm run build && npx playwright test` | Needs `scripts/dev-chain.sh` running. Starts the API and the web server itself |

Results on the development machine (Windows 11, Node 22.11, Python 3.12, Foundry 1.9.0) when this
README was written:
- Backend: 105 passed, 7 skipped (Anvil/forge-marked tests without a running chain).
- CLI package: 99 passed, 1 skipped (the network test, which passed separately in about 97 s).
- Forge: 20 passed, 6 skipped (the env-driven scenario entry points).
- Vitest: 18 passed.
- Playwright: 2 passed (the desktop workflow and the mobile navigation drawer).

The Docker images and the GitHub Actions workflow have **not** been run yet. See
[FEEDBACK.md](FEEDBACK.md).

## Repository layout

```
backend/    FastAPI app, simulation runner, LP math, AI, reports, Alembic migrations
packages/hooklens/  Shared analysis engine + `hooklens` CLI (local scanner, HTML/JSON/SARIF reports)
action.yml  Composite GitHub Action running the CLI
examples/   Example GitHub Actions workflow
contracts/  Foundry project: fixture hooks, actor harness, scenarios, invariants, deploy script
frontend/   Next.js App Router UI (TypeScript strict, Tailwind v4, TanStack Query, Zod)
docker/     Backend (app + sim targets) and frontend Dockerfiles
docs/       Architecture, threat model, methodology, API, deployment, limitations
scripts/    dev-chain.sh
```

## Documentation

- [CLI and GitHub Action](docs/cli.md)
- [Architecture](docs/architecture.md)
- [Threat model](docs/threat-model.md)
- [Analyzers](docs/analyzers.md)
- [Simulation methodology](docs/simulation-methodology.md)
- [LP math](docs/lp-math.md)
- [API](docs/api.md)
- [Frontend: UI architecture and real-data rules](docs/frontend.md)
- [Deployment](docs/deployment.md)
- [Limitations](docs/limitations.md)
- [Build feedback](FEEDBACK.md)
- [Contributor guide for AI assistants](CLAUDE.md)

## License

No license has been chosen yet. Until one is added, the default copyright rules apply.
