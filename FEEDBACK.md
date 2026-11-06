# Build feedback

These are observations from building HookLens: problems actually hit, how each was resolved, and
what is still unverified. Nothing here is a user survey or a third-party review. HookLens has
not had external users yet.

Environment: Windows 11, Git Bash, Node 22.11.0, Python 3.12 (uv), Foundry 1.9.0, Next.js 16,
v4-periphery `c6e4754`, v4-core `59d3ecf`.

## Uniswap v4 / Foundry

- **Nested `WrappedError` reverts.**
  - *Observed:* when a hook reverts inside a callback, the PoolManager wraps the reason in
    `WrappedError(target, selector, reason, details)`. Without recursive decoding, the lab showed
    only an opaque selector for the oracle-gated fixture.
  - *Fix:* `backend/app/simulation/decode.py` now unwraps recursively. The UI now shows
    "HookLens: mocked oracle revert" on the failing frame.
- **Fork URL exposure in argv.**
  - *Observed:* `forge test --fork-url <url>` puts the RPC URL, often with an API key in its path,
    on the command line, where other local processes can see it.
  - *Fix:* an `[rpc_endpoints] hooklens_fork = "${HOOKLENS_FORK_RPC_URL}"` alias plus an env
    allowlist. Stored repro commands also use the alias.
- **Hook address bits.** Fixture hooks have to be deployed at addresses whose low 14 bits match
  their permissions. The fixture deployer mines salts with v4-periphery's `HookMiner`. The
  generated permission constants are tested against the vendored `Hooks.sol`, so a v4-core bump
  that changes the flags fails CI instead of silently mis-decoding.
- **Scenario entry points skip under a plain `forge test`.** This is by design (6 skipped): they
  need backend-provided env. The same logic is covered locally by `FixtureScenarios.t.sol`.

## Next.js 16

- **`require(esm)` on Node 22.11.**
  - *Observed:* `next build` failed because Tailwind v4's `@tailwindcss/node` loads ESM-only
    dependencies through `require()`, and Node 22.11 does not support that without a flag. Vitest's
    jsdom environment hit the same problem.
  - *Root cause:* passing `--experimental-require-module` on the CLI did not reach Turbopack's
    worker processes.
  - *Fix:* `frontend/scripts/compat.mjs` sets `NODE_OPTIONS` for Node 22.0–22.11 only. Node 22.12
    and later need nothing.
- **`cacheComponents` and client hooks.**
  - *Observed:* with `cacheComponents: true`, `useParams` and `useSearchParams` must render inside
    `<Suspense>`.
  - *Fix:* every dynamic route became a server `page.tsx` wrapping a client `view.tsx`.
- **`LayoutProps` types.** The global `LayoutProps` type only exists after `next typegen`, so
  `npm run typecheck` runs it first.
- **Rewrites resolve at build time.**
  - *Observed:* the API proxy target can't be changed at container start.
  - *Fix:* `HOOKLENS_API_URL` is a Docker build arg.
- **SSE through the proxy.** Next's response compression is turned off (`compress: false`) so that
  SSE through the rewrite proxy is not held back. Through the proxy, the first event arrived in
  about 0.26 s.

## Bugs found by our own tests

- **Permission-preview decode failure** (found by Playwright).
  - *Observed:* the scan form's permission preview said "Could not decode" for valid addresses.
  - *Root cause:* the decode endpoint's flags have no `explanation` field, and the frontend's Zod
    schema required one.
  - *Fix:* the field is now optional, and the UI shows the actual error message.
- **Lab run details not rendering** (found by Playwright).
  - *Observed:* scenario runs never showed their details.
  - *Root cause:* the frontend's terminal-status set covered job statuses but not scenario
    statuses (`expected_revert`, `unexpected_revert`, …).
  - *Fix:* the condition is now "not queued or running".
- **Silent loss of invalid `price_moves`.**
  - *Observed:* invalid values were dropped without telling the caller.
  - *Fix:* they are now rejected with 422 (each value must be in (−100%, +10 000%], at most 21
    values).
- **mypy findings** (found when adding mypy to CI).
  - *Observed:* 25 errors, all type-narrowing (Optional values that were already checked at
    runtime, and a reused loop variable). None changed behaviour.
  - *Fix:* all corrected, and mypy is now part of the backend CI job.
- **Anvil integration tests could skip silently in CI.**
  - *Fix:* `HL_TEST_ANVIL=1` now turns a missing chain or forge into a hard error.

## Windows development notes

- Python's default `cp1252` encoding misreads UTF-8 output (for example, `±` printed as `Â±`). It
  looked like a source bug but wasn't. Read files with `encoding="utf-8"`.
- Stopping a background `npm run start` did not kill its child `node` process, so a stale server
  kept port 3000. Kill by port: `Get-NetTCPConnection -LocalPort 3000` → `Stop-Process`.

## Not yet verified

- **Docker.** Docker was not installed on the development machine. The Compose file parses, but
  none of the images (`app`, `sim`, `frontend`) has been built or run. The backend Dockerfile's uv
  image was bumped to 0.12 to match the version that wrote `uv.lock`; that was a precaution, not a
  fix for an observed failure.
- **GitHub Actions.** `.github/workflows/ci.yml` has not run yet. Every step in it has been run
  locally, except `npx playwright install --with-deps` and the Docker job.
- **Mainnet and external services.** No mainnet RPC, Etherscan key or Anthropic key was
  configured.
  - The resolver, pool discovery and fork runner share their code paths with chain 31337, and those
    are tested against local Anvil. Mainnet-specific behaviour has not been run: archive-state
    errors, provider rate limits, and Etherscan v2 source retrieval and compilation of real
    verified hooks.
  - The Etherscan provider has **no automated test**.
  - The AI flow is tested with a deterministic fake provider (`backend/tests/test_ai.py`), not
    against the Anthropic API.
