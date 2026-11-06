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
- **Scans failing on load-balanced RPCs** (found by a live Sepolia scan).
  - *Observed:* a scan on a public Sepolia RPC failed with `archive_state_unavailable`.
  - *Root cause:* HookLens pinned the head block and then asked for code at it. The next request
    reached a backend node that had not imported that block yet ("block not found"), and the RPC
    client classifies that message as missing archive state.
  - *Fix:* when no block is given, non-local chains now pin `head - 2` (`pin_confirmations`).
    Anvil still pins its head.
- **Pool discovery impossible on free RPC plans** (found by live Sepolia scans).
  - *Observed:* Alchemy's free plan rejects `eth_getLogs` over more than 10 blocks, answering with
    HTTP 400. HookLens reported that as a generic "HTTP 400". Sepolia's v4 history is about
    4.8 million blocks, roughly 480,000 requests at that size.
  - *Fix:* the RPC client now reads JSON-RPC error bodies on HTTP 4xx responses, so range limits
    are recognised. Discovery then falls back to Etherscan v2 `logs/getLogs`, paging by block and
    de-duplicating at page boundaries. A live Sepolia scan found 114 pools for one hook this way.
- **Owner detection picked the wrong role** (found by a live Sepolia fork simulation).
  - *Observed:* for a verified hook with both an OpenZeppelin `_owner` and a `factory` variable,
    HookLens chose `factory` as the owner. The lab's "authorized" admin calls then reverted with
    `OwnableUnauthorizedAccount`.
  - *Root cause:* the first address-typed role variable found was taken as the owner.
  - *Fix:* use `owner()` at the pinned block when the source exposes it. Otherwise rank owner-named
    variables first, then other role names, then the variable most used by access checks. After the
    fix, the same simulation's authorized calls succeed.
- **False accounting failure for fee-forwarding hooks** (found by a live mainnet fork simulation).
  - *Observed:* on a Clanker pool, the accounting scenario reported 7 "failed" invariants, labelled
    `observed=revert` although nothing reverted.
  - *Root cause:* the harness's own comment said tokens leaving the tracked set {actors,
    PoolManager, hook} should be reported, not failed, but the code recorded them as failed LP
    expectations. Clanker forwards fees to an external recipient, while every trader's balance still
    matched its BalanceDelta.
  - *Fix:* a BalanceDelta mismatch remains a failure. Value leaving the tracked set is now an
    `outflow_*` observation with the net amounts. Re-run: 19/19 steps met their expectations.
- **Anvil integration tests could skip silently in CI.**
  - *Fix:* `HL_TEST_ANVIL=1` now turns a missing chain or forge into a hard error.

## CLI and local scanner

- **Logic behind a `BaseHook` dispatcher was invisible** (found by the fixture tests).
  - *Observed:* the OpenZeppelin-style `BaseHook` implements `beforeRemoveLiquidity` and forwards
    it to an internal virtual `_beforeRemoveLiquidity`. The AST index resolved that internal call
    to the base declaration, an empty function, so a withdrawal lock in the override was not
    found.
  - *Fix:* internal calls now resolve to the most-derived override (`baseFunctions`
    linearisation). Explicit `super.` calls are left alone.
- **False withdrawal finding from `onlyPoolManager`** (found by scanning
  uniswapfoundation/v4-template).
  - *Observed:* the access guard was reported as a withdrawal revert condition on `Counter`.
  - *Root cause:* `if (msg.sender != poolManager) revert NotPoolManager();` was recorded twice:
    once as a guarded revert and once as an unconditional revert.
  - *Fix:* reverts nested in an `if` are no longer also recorded as bare reverts. After the fix,
    Counter has only an informational finding.
- **Shallow submodule clone failed on v4-template.**
  - *Root cause:* a submodule pins a commit that a depth-1 fetch cannot reach.
  - *Fix:* fall back to a full-depth submodule update.
- **Deep submodule chains on Windows** (found by scanning v4-template from the installed wheel).
  - *Observed:* recursive submodule checkout failed with `Filename too long`, then `'$GIT_DIR' too big`,
    six levels deep in test-only dependencies
    (`lib/uniswap-hooks/lib/v4-periphery/lib/v4-core/lib/openzeppelin-contracts/lib/forge-std/lib/ds-test`).
    The scan still compiled, because the hook only needs the top-level libraries, but the warning
    claimed submodules "could not be fetched".
  - *Fix:* git runs with `core.longpaths=true`. A path-length failure skips the useless full-depth
    retry, and the note names exactly which nested submodules are missing.
  - *Follow-up bug:* `shutil.rmtree` could not delete the resulting long paths, which left partial
    temp directories behind. Cleanup now uses the `\\?\` extended-length prefix on Windows, and
    the network test asserts that no temp directory remains.
- **HTML report blocked by its own CSP.** Inline `style=` attributes are covered by `style-src`,
  so the hashed-style CSP blocked them. They were replaced by classes and an SVG severity bar.
  A test now asserts there are no `style="` attributes.
- **Mangled job summary on Windows** (found by the action test).
  - *Observed:* `hooklens summary > file` wrote cp1252 bytes, so `·` became `0xB7` and emoji
    became `?`.
  - *Fix:* redirected stdout and stderr are always UTF-8.
- **Invalid `action.yml`** (found by the action test). Unquoted descriptions containing
  `: ` (e.g. ``needs `security-events: write` ``) are YAML mapping syntax. GitHub would have
  rejected the action.
- **Invalid generated workflow.** `hooklens init --github-action` rendered `paths: ['src']`, a
  Python list repr. Action inputs are strings; it now renders `paths: src`.
- **PyPI name taken.** `hooklens` on PyPI is an unrelated project, so the documentation installs
  from Git and the release workflow publishes only when explicitly enabled.

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
- **GitHub Actions.** Neither `.github/workflows/ci.yml`, `release-cli.yml` nor the composite
  `action.yml` has run on GitHub yet. The action's scan, summary and gate scripts were run locally
  under Git Bash by `packages/hooklens/tests/test_action.py`; the SARIF upload, artifact upload
  and PR comment steps were not. The Docker image change that copies `packages/hooklens` is also
  unbuilt. Every other step of `ci.yml` has been run locally, except
  `npx playwright install --with-deps` and the Docker job.
- **Mainnet and external services.** No mainnet RPC, Etherscan key or Anthropic key was
  configured.
  - The resolver, pool discovery and fork runner share their code paths with chain 31337, and those
    are tested against local Anvil. Mainnet-specific behaviour has not been run: archive-state
    errors, provider rate limits, and Etherscan v2 source retrieval and compilation of real
    verified hooks.
  - The Etherscan provider has **no automated test**.
  - The AI flow is tested with a deterministic fake provider (`backend/tests/test_ai.py`), not
    against the Anthropic API.
