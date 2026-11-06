# API

The API serves everything under `/v1`. In the browser it is reached as `/api/v1/*` through the
Next.js proxy. The live OpenAPI schema is at `/openapi.json`, with interactive docs at `/docs`. A
snapshot is checked in at `frontend/openapi.json`, and the frontend's types are generated from it
with `npm run gen:api`.

## Conventions

- **Workspace.** The first response sets an `hl_ws` HttpOnly cookie. API clients can send the
  same token as `X-HookLens-Workspace`. Scans, simulations and reports are scoped to the workspace.
- **Errors.** Errors are `application/problem+json` objects with these fields:
  - `type` (`urn:hooklens:error:<code>`)
  - `title`, `status`, `code`, `detail`, `details`
  - `retryable`
  - `correlation_id`
- **Correlation.** Every response carries `X-Correlation-ID`. A 429 also carries `Retry-After`.
- **Pagination.** List endpoints take `?limit=` (1–100, default 20) and `?offset=`, and return
  `{items, total, limit, offset}`.
- **Jobs.** Endpoints that start work return `202` with a `job_id`. Follow it with
  `GET /v1/jobs/{id}/events`, an SSE stream of `progress` events and a final `end` event, or poll
  `GET /v1/jobs/{id}`. Cancel with `POST /v1/jobs/{id}/cancel`.
- **Rate limits.** There is a general per-client limit and a stricter one on job creation.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/health`, `/v1/health/worker` | Liveness, and job-backend health |
| GET | `/v1/chains` | Supported chains, whether their RPC is configured, the source-verification method, and whether AI is enabled |
| GET | `/v1/permissions/decode?address=` | Decode the permission bits of any address (pure, no RPC) |
| POST | `/v1/hooks/resolve` | Resolve an address at a block: code, proxy and source status, without analysis |
| POST | `/v1/scans` | Start a scan: `{chain_id, hook_address, pool_id?, block_number?, discover_pools?}` |
| GET | `/v1/scans`, `/v1/scans/{id}` | List scans, or get one scan with its contract, permissions, pools and analyzer runs |
| GET | `/v1/scans/{id}/findings[/{finding_id}]` | Findings |
| GET | `/v1/scenarios` | The scenario catalogue |
| POST | `/v1/scans/{id}/simulations` | Plan and run scenarios on a fork |
| GET | `/v1/scans/{id}/simulations`, `/v1/simulations/{id}` | Simulations and their run summaries |
| GET | `/v1/simulations/{id}/runs/{run_id}` | One scenario run: steps, decoded trace, repro command |
| GET | `/v1/evidence?scan_id=` | Search a scan's evidence: `q`, `kind`, `basis`, `function`, `simulation_id`, `ids` (comma-separated), with `limit` up to 200 |
| GET | `/v1/evidence/{scan_id}/{evidence_id}` | One evidence record |
| POST | `/v1/positions/compare` | LP baseline, hypothetical price moves and measured simulation effects |
| GET | `/v1/positions/{id}` | A stored comparison |
| POST / GET | `/v1/scans/{id}/reports` | Generate a report, or list reports |
| GET | `/v1/reports/{id}`, `/v1/reports/{id}/pdf` | The JSON report (with `content_hash`), or the PDF |
| POST / GET | `/v1/scans/{id}/findings/{finding_id}/explanations` | Request an AI explanation, or list them. Returns `unavailable` without an Anthropic key |

## Example

```bash
curl -s -X POST localhost:8000/v1/scans -H 'content-type: application/json' \
  -c ws.txt -d '{"chain_id":31337,"hook_address":"<hook_oracle_gated.address>"}'
curl -sN -b ws.txt localhost:8000/v1/jobs/<job_id>/events
curl -s -b ws.txt localhost:8000/v1/scans/<id>/findings
```
