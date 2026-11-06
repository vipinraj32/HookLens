# Frontend: UI architecture and data rules

The web UI is a Next.js App Router app in `frontend/`. It talks only to the HookLens API: the
browser calls `/api/v1/*`, and Next rewrites those calls to FastAPI (`HOOKLENS_API_URL`, default
`http://127.0.0.1:8000`). RPC endpoints, API keys and secrets never reach the browser.

## Real-data rules

These rules hold everywhere in the product UI (`/app/**` and the live parts of `/`):

1. **No mock data.** Every number, status, finding, step, trace and token amount comes from an API
   response. When the server has no value, the UI says so ("not recorded", "unknown",
   "unavailable") or hides the field. Nothing is filled in with placeholders.
2. **One illustrative exception.** The landing-page lifecycle diagram
   (`components/landing/hook-lifecycle.tsx`) explains how Uniswap v4 calls hooks in general. It is
   labelled "Illustrative flow, not a live transaction" and reads no chain data. The permission
   decoder on the landing page computes from the address the user types and calls no backend.
3. **Static vs. executed.** Findings are static indicators for review. Lab results are forge
   outcomes at one fork and block. The UI never presents a finding as a confirmed exploit, and
   never presents an empty result as "safe".
4. **Unknown stays unknown.** If source analysis was unavailable (bytecode-only hooks), the
   permission matrix and the control profile show "unknown", not "no finding".
5. **Infrastructure outcomes are not findings.** `infra_error`, `timed_out` and `cancelled` runs carry
   a notice saying that nothing can be concluded about the hook. `unsupported` and `skipped`
   scenarios are shown as not applicable.
6. **Hypothetical inputs are labelled.** In LP Exposure, the user's range and the price moves are
   tagged `hypothetical`. Pool state is tagged `on-chain`, simulation effects are tagged `measured`,
   and missing inputs are tagged `unavailable`. Market moves are never called hook losses.
7. **Validated responses.** Every response is parsed with a Zod schema (`src/lib/api/models.ts`)
   before it is used. A schema mismatch is shown as an error state.

## Brand

The official kit is in `frontend/src/app/assest/`. The UI uses these assets:

| Asset | Source in the kit | Used for |
|---|---|---|
| `public/brand/hooklens-logo-dark.svg` | "Primary signature / dark": magenta symbol and white wordmark, cropped to its two paths (no recolouring) | Landing header and footer, app sidebar, mobile header |
| `public/brand/hooklens-symbol.svg` | `pink_Symbol.svg` | Small marks (hero eyebrow, 404) |
| `src/app/icon.svg`, `apple-icon.png`, `favicon.ico` | `hooklens-app-icon.svg` / `@2x.png` | Browser and app icons |
| `src/app/opengraph-image.png` | `hooklens-social-avatar@2x.png` | Link previews |

`header_logo.png` and `black_Symbol` have a near-black wordmark or symbol and disappear on the dark
UI. `Primary signature`, `REVERSED`, `MONOCHROME` and `Clear space guidance` are specimen boards
with labels, not embeddable logos. `components/brand.tsx` is the only place that renders the logo.
It keeps the source aspect ratio and the clear space the kit asks for (at least ¼ of the symbol
height).

Colours come from the kit: magenta `#FF0099` (accent), ink `#17141B` (surface), `#BDB5C1`
(muted text) and `#716B75` (borders only, because it is below AA contrast as text). Text on magenta
is ink, not white: white on `#FF0099` is 3.7:1, ink is 5.3:1.

## Layout

```
src/app/page.tsx                 landing: hero, live server status, lifecycle diagram, decoder, checks
src/app/app/layout.tsx           Providers (TanStack Query) + AppShell
src/app/app/page.tsx             Overview: next actions from the latest real scan, chains, scans
src/app/app/scan/page.tsx        Hook Scanner: chain, address, optional pool and block, live job stages
src/app/app/scans/page.tsx       Hook Intelligence index (scan list)
src/app/app/scans/[id]/view.tsx  Hook Intelligence: findings (search/filter), permission matrix, pools,
                                 contract, analyzer coverage, reports. ?tab= and ?finding= deep links
src/app/app/lab/page.tsx         Adversarial Lab index: scenario catalogue + scans to open
src/app/app/scans/[id]/lab/view.tsx  Lab: run form, simulation history, step timeline, step detail,
                                 invariants, fork context. ?scenario= preselects a scenario
src/app/app/lp/view.tsx          LP Exposure: exact v4 math, range bar, tagged values, price scenarios
src/app/app/reports/page.tsx     Workspace reports (GET /v1/reports)
src/app/app/reports/[id]/view.tsx  Report: findings filter/search, copy IDs, runs, JSON/PDF export
src/app/app/evidence/view.tsx    Evidence explorer
```

Shared components:

| Component | Purpose |
|---|---|
| `components/shell.tsx` | Sidebar nav, top header with breadcrumbs and the network selector, mobile drawer |
| `components/ui.tsx` | Buttons, cards, badges, copy buttons, empty/error/skeleton states, form fields |
| `components/scan-table.tsx` | Paginated scan list used by Overview, Hook Intelligence and the Lab index |
| `components/permission-matrix.tsx` | Operation × before/after/return-delta matrix; callback detail, related findings, evidence and lab links; control profile |
| `components/lab.tsx` | `StepTimeline`, `StepDetail` (expected vs observed, revert, token deltas, gas, events, trace), `InvariantPanel`, `ForkContext` |
| `components/trace.tsx` | Expandable call tree; frames that are hook callbacks on the scanned hook are highlighted |
| `components/range-bar.tsx` | Position range vs current tick |
| `components/job-progress.tsx` | SSE/polling job log, the stages the backend reported, cancel |
| `components/landing/hook-lifecycle.tsx` | Illustrative v4 call-flow diagram with step-through |
| `components/landing/live-status.tsx` | Live server facts (chains with RPC status, Foundry, scenario count) |
| `components/landing/hero-pipeline.tsx` | Illustrative hero pipeline (address → intelligence → lab → LP), labelled "no live data" |
| `components/brand.tsx` | `BrandLogo`, `BrandMark`, `BrandHomeLink` |
| `components/workflow.tsx` | Workflow stepper (address → intelligence → pools → lab → evidence → LP → report), derived from the scan, its simulations and its reports. LP exposure is never shown as done, because it is not stored |
| `components/scenarios.tsx` | Scenario cards with LP rationale, `OutcomeBadge`, `OutcomeLegend`, `Elapsed` |
| `lib/outcomes.ts` | Groups forge statuses into Passed / Failed / Inconclusive / Not run / Error. It never upgrades a status, and `unsupported` is never shown as passed |

### Network selector

The header's network selector stores a chain ID in `localStorage` (`src/lib/network.ts`). It filters
the Overview, Hook Intelligence, Lab and Reports lists (the `chain_id` query parameter), and it
pre-selects the scanner's chain. It does not change which RPC the server uses.

### Token amounts

Lab step deltas (`amount0`, `amount1`) are v4 `BalanceDelta` values from the acting account's side:
negative means paid into the pool, positive means received. The UI shows the raw integer and an exact
decimal rendering (`formatUnits` in `src/lib/format.ts`, BigInt-free string math, no floating point)
using the pool's token decimals. When decimals are unknown, only the raw value is shown.

### Invariants

The invariant panel lists only what the harness evaluated: steps with `phase == "invariant"`, and the
per-step `metrics` (`actor_delta_matches`, `value_conserved`, hook claim changes) that the
accounting scenario records. If neither exists for a run, the panel is not rendered.

## API integration

- `src/lib/api/client.ts`: fetch wrapper with a timeout, an AbortSignal, retries for transient GET
  failures, and normalised errors.
- `src/lib/api/hooks.ts`: TanStack Query hooks. Scans poll every 3 s until they reach a terminal
  status, and jobs stream over SSE with a polling fallback (`src/lib/api/jobs.ts`).
- Backend addition for this UI: `GET /v1/reports` (workspace-scoped, paginated, optional
  `chain_id`). It returns report metadata plus the scan's `chain_id` and `hook_address`, and never
  the report content. A test is in `backend/tests/test_jobs_api.py`.

## Running locally

```bash
bash scripts/dev-chain.sh                                    # Anvil + fixture hooks (Git Bash on Windows)
cd backend && uv run uvicorn app.main:app --port 8000
cd frontend && npm ci && npm run dev                         # http://localhost:3000
```

Checks:

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
cd frontend && npx playwright test        # needs the chain running; starts API and web if needed
```

The e2e workflow skips the "Explain this finding" click when the server has an AI key configured,
so the test run never makes a paid model call.
