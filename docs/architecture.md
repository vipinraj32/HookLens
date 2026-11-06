# Architecture

```
Browser ──► Next.js (frontend, :3000) ──/api/v1/*──► FastAPI (api, :8000)
                                                    │  writes jobs + results
                                                    ▼
                                              Postgres / SQLite
                                                    ▲
             Redis (Celery broker) ◄── dispatch ────┘
                │
     ┌──────────┴───────────┐
     ▼                      ▼
 worker (-Q default)    sim-worker (-Q sim)  ── forge test --fork-url ──► RPC (mainnet) / Anvil (31337)
 scans, reports, AI     simulations only
```

## Request path

- The browser only talks to the Next.js server.
- `next.config.ts` rewrites `/api/v1/:path*` to `${HOOKLENS_API_URL}/v1/:path*`. Next.js resolves
  rewrites at build time, which is why the frontend Dockerfile takes `HOOKLENS_API_URL` as a build
  argument.
- Compression is turned off in Next.js so Server-Sent Events are not buffered by the proxy.
- The API sets an anonymous workspace cookie (`hl_ws`, HMAC-signed). That cookie scopes ownership
  of scans, simulations and reports. It is not authentication.

## Jobs

The `jobs` table is the source of truth. It holds:
- status
- progress
- the step log
- the cancel flag
- attempts
- the heartbeat
- partial results

The two dispatchers only decide where a handler runs:

| Backend | Used for | Behaviour |
|---|---|---|
| `local` | development, tests, CI | In-process thread pool |
| `celery` | Docker | `send_task("hooklens.run_job", queue=...)`. Simulations are routed to the `sim` queue (the hardened worker) and everything else to `default` |

State machine:
- `queued → running → completed | partial | failed | cancelled | timed_out`.
- `running → queued` is a retry. It happens only for errors marked retryable, such as RPC
  timeouts.

Reliability mechanisms:
- **Heartbeats.** Handlers send them.
- **Reaper.** It marks jobs whose heartbeat is older than `job_heartbeat_timeout_s` as `failed`
  (`worker_lost`). It runs at API startup, and periodically under Celery beat. With the local
  backend, jobs orphaned by a crash are reaped only on the next API start.
- **Cancellation.** It is cooperative: a handler checks the flag between steps, and the forge
  runner kills its subprocess.

Progress streaming:
- `GET /v1/jobs/{id}/events` streams progress as SSE (`progress`, then a final `end`).
- The frontend falls back to polling `GET /v1/jobs/{id}` if the stream fails.

## Scan pipeline (`app/services/scan_service.py`)

1. **Resolve** (`resolver.py`, `rpc.py`, `evm.py`):
   - Validate the address, pin the block, read code, and detect proxies.
   - Get source from Etherscan, or match it to a local artifact.
   - Discover pools.
2. **Analyze** (`analyzers/runner.py`). Each analyzer runs in isolation: a crash records an
   `analyzer_error` run and the scan finishes as `partial`.
3. **Persist** the contract, scan, findings, evidence and analyzer runs.

## Simulation pipeline (`app/simulation/`)

- `planner.py` maps permissions, facts and findings to a `ScenarioPlan` for each scenario: whether
  it applies, the reason, the `HL_*` env vars, and notes.
- `forge_runner.py` runs `forge test --match-contract …` once per scenario as a subprocess. See the
  [threat model](threat-model.md).
- `traces.py` and `decode.py` turn forge JSON traces into call trees with decoded reverts. Decoding
  covers nested `WrappedError`s and custom errors from local artifacts and known v4 selectors.
- `interpret.py` derives observed findings (confidence basis `simulation`) from scenario results.

## Frontend

- Next.js 16 App Router with `cacheComponents`.
- Each dynamic route is a server `page.tsx` that renders a client `view.tsx` inside `<Suspense>`.
- Data access goes through `src/lib/api`:
  - Responses are validated with Zod.
  - Errors are parsed from `problem+json`.
  - Requests use AbortSignal timeouts.
  - Only GET requests are retried.
- Types are generated from the API's OpenAPI schema (`npm run gen:api`).
