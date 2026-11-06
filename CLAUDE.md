# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## What this is

HookLens is a Uniswap v4 hook analysis tool with two front ends over **one analysis engine**:

- **Web app**: FastAPI backend (`backend/`) and Next.js UI (`frontend/`). It resolves deployed
  hooks over RPC, runs the analyzers, Foundry fork simulations (`contracts/`), LP math, AI
  explanations and reports.
- **CLI and GitHub Action**: the `hooklens` package (`packages/hooklens/`) plus `action.yml`. It
  is a local-first static scanner for Solidity source, with HTML, JSON and SARIF reports.

The analyzers live in `packages/hooklens/src/hooklens/analyzers/`. The backend imports them as
`hooklens.analyzers` through a uv path dependency (`backend/pyproject.toml` →
`[tool.uv.sources]`). **Never fork or duplicate analyzer logic into the backend or the CLI.**
Change it once, in the package.

## Layout

```
packages/hooklens/   shared engine + CLI
  src/hooklens/analyzers/   analyzers, permission decoder, bytecode, AST index (shared)
  src/hooklens/local/       project discovery, imports/remappings, solc compile, hook detection
  src/hooklens/scanner.py   source-mode scan -> canonical report dict (schema v1)
  src/hooklens/reports/     html / sarif / markdown renderers (all from the canonical report)
  src/hooklens/remote.py    GitHub acquisition (hardened git clone, tarball fallback)
  src/hooklens/lab.py       `hooklens lab` client for the backend simulation API
  src/hooklens/cli.py       Click entry point
  tests/                    pytest; fixture hooks in tests/fixtures/sample-hooks
backend/             FastAPI app, jobs, resolver, simulation runner, LP math, AI, reports
contracts/           Foundry project: fixture hooks, harness, scenarios (submodules in lib/)
frontend/            Next.js App Router UI
action.yml           composite GitHub Action that runs the real CLI
docs/                architecture, analyzers, cli, methodology, limitations, ...
```

## Commands

Run `git submodule update --init --recursive` first. The tests need v4-core sources.

| Area | Command (from the directory shown) |
|---|---|
| CLI package | `packages/hooklens`: `uv sync && uv run pytest` |
| CLI lint/types | `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src` |
| Real-repo network test | `HOOKLENS_TEST_NETWORK=1 uv run pytest -m network` (clones uniswapfoundation/v4-template, ~100 s) |
| CLI build | `uv build && uvx twine check --strict dist/*` |
| Backend | `backend`: `uv sync && uv run pytest`; `uv run ruff check . && uv run ruff format --check . && uv run mypy app` |
| Backend integration | `HL_TEST_ANVIL=1 uv run pytest -m "anvil or forge"` (needs `scripts/dev-chain.sh` running) |
| Contracts | `contracts`: `forge build && forge test` |
| Frontend | `frontend`: `npm ci && npm run lint && npm run typecheck && npm test && npm run build` |
| Try the CLI | `packages/hooklens`: `uv run hooklens scan ../../contracts --local --html report.html` |

After editing analyzers, run **both** the package tests and the backend tests.
`backend/scripts/gen_permissions.py` regenerates
`packages/hooklens/src/hooklens/analyzers/permissions_generated.py` from the vendored `Hooks.sol`.
Never hand-edit the generated file.

## Rules that must hold

- **Honesty of results.** Findings are static indicators that need review. Never describe them
  as confirmed exploits. Never say a hook is "safe", "audited" or "secure", and never say that
  no findings means safe. Keep static results separate from execution-tested ones
  (`execution_results` is `null` in static scans).
- **No fabrication.** Do not invent stats, findings, test results, audits, feedback or file
  locations. SARIF results without an in-project location get none. FEEDBACK.md records only
  things that were actually observed.
- **Stable identifiers.** Finding ids (`HL-…`), rule ids (`HL.<CODE>.<rule>`) and the JSON
  schema are public contracts. Do not change the inputs that make up an id. Breaking schema
  changes need a `schema_version` bump and an update to `src/hooklens/schema/report-v1.schema.json`.
- **Exit codes.** 0 ok, 1 findings ≥ `--fail-on`, 2 config/usage, 3 source, 4 analysis or partial
  scan, 5 report, 130 interrupted. A scanner error must never look like a clean scan or like a
  finding.
- **Never execute scanned repositories.** No `forge`, `npm`, Makefiles or scripts from a scanned
  repo. Git keeps the hardened options in `remote.GIT_SAFE`. Imports may not leave the project
  root unless a remapping given on the CLI allows it. A `hooklens.toml` in a remote repo is
  untrusted (its outputs and `fail_on` are ignored).
- **HTML report.** Standalone and offline: no external URLs. All text is escaped. The CSP pins
  the inline style and script by hash, so use no inline `style=` attributes or event handlers.
- **GitHub Action.** Inputs reach shell scripts only through `env:`, never `${{ }}` inside `run:`
  (a test enforces this). Privileged steps stay skipped for fork PRs. No hardcoded tokens.
- **Secrets.** Never print or commit `.env` values, RPC URLs with keys, or tokens. Never ask for
  private keys or seed phrases. RPC endpoints come only from server config, never from users.
- **Fixtures.** Hooks in `contracts/src/fixtures/` and `packages/hooklens/tests/fixtures/` are
  deliberately flawed test fixtures, not examples of good practice or real deployments.

## Conventions

- Python ≥ 3.11, ruff (line length 120), mypy (non-strict, but `uv run mypy src` / `mypy app` must be clean); Solidity 0.8.26 / cancun for fixtures.
- New analyzer rules need an entry in `hooklens/rules_catalog.py` and a fixture-based test that
  asserts both a true positive and the absence of a false positive.
- Prefer small, targeted changes. Do not commit or push unless asked. Branch off `main` first.
- The PyPI name `hooklens` belongs to an unrelated project. Do not rename the package, and do not
  tell users to `pip install hooklens`. Install from Git or a wheel.
- There is no LICENSE yet. Do not add license metadata or pick a license without the maintainer.

## Windows notes

- Development happens on Windows. Use Git Bash for `scripts/*.sh`. Read and write text with
  `encoding="utf-8"`. The CLI forces UTF-8 when output is redirected.
- Deep submodule chains can hit git's path limits. Clones use `core.longpaths=true`, and cleanup
  uses the `\\?\` prefix.
