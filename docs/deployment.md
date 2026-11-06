# Deployment

> The Compose stack and Dockerfiles have been validated structurally (`docker compose config`
> parses them on a machine with a YAML parser), but the images had **not** been built or run when
> this was written, because Docker was not available on the development machine. CI builds them.
> Treat the first `docker compose up` as a test.

## Prerequisites

- Docker with Compose v2.
- Initialised submodules: `git submodule update --init --recursive`. The backend image build fails
  early with a clear message if `contracts/lib` is empty.
- A `.env` copied from `.env.example`:

| Variable | Required | Notes |
|---|---|---|
| `HOOKLENS_WORKSPACE_SECRET` | yes | ≥ 32 random characters. The API refuses to start in production otherwise. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_PASSWORD` | yes | |
| `HOOKLENS_MAINNET_RPC_URL` | for mainnet | An archive node is needed for historical blocks and forks |
| `HOOKLENS_SEPOLIA_RPC_URL` | for Sepolia | Pool discovery needs logs from block 7,258,946: a plan without tight `eth_getLogs` range caps, or an Etherscan key for the fallback |
| `HOOKLENS_ETHERSCAN_API_KEY` | optional | Enables verified source and therefore the source-AST analyzers |
| `HOOKLENS_ANTHROPIC_API_KEY` | optional | Enables AI explanations (`HOOKLENS_AI_MODEL`, default `claude-opus-5-5`) |
| `HOOKLENS_ENABLE_LOCAL_CHAIN` | optional | `true` with the `dev-chain` profile |
| `HOOKLENS_CORS_ORIGINS`, `HOOKLENS_LOG_LEVEL`, `HOOKLENS_WEB_PORT` | optional | |

A key left blank (`KEY=`) means the feature is not configured.

## Services

| Service | Image target | Role | Networks |
|---|---|---|---|
| `postgres`, `redis` | upstream | Storage and Celery broker | internal |
| `migrate` | `app` | `alembic upgrade head`, run once | internal |
| `api` | `app` | FastAPI on :8000. Not published; reached through the frontend proxy | internal, egress |
| `worker` | `app` | Celery `-Q default`: scans, reports, AI | internal, egress |
| `beat` | `app` | Periodic stale-job reaper | internal |
| `sim-worker` | `sim` | Celery `-Q sim`: Foundry simulations. Has `forge`, `anvil`, `cast` and the solc that compiled the project (no runtime download) | internal, egress |
| `frontend` | frontend | Next.js standalone server, read-only rootfs, published on `HOOKLENS_WEB_PORT` | internal, egress |
| `anvil`, `fixtures` | `sim` | Profile `dev-chain`: a local chain, and a one-shot fixture deploy into the shared `deployments` volume | internal |

The frontend proxies to `http://api:8000`. That value is baked in at build time (the
`HOOKLENS_API_URL` build arg) because Next.js evaluates rewrites during the build.

## Operations

- **Logs** are JSON lines with `correlation_id`, and secrets are redacted.
- **Health.** `GET /v1/health` serves as the API healthcheck. `GET /v1/health/worker` reports
  dispatcher (Celery) health, forge availability, whether AI is enabled, and per-chain RPC
  configuration.
- **Scaling.** Run more `worker` replicas freely. Keep `sim-worker` at concurrency 1 per container
  and scale by adding replicas. Rate limiting is per API process, so with several API replicas,
  enforce limits at the proxy.
- **Upgrades.** `migrate` runs before `api` and the workers start.
- **Egress.** Restrict `sim-worker` egress to the RPC host at the network layer. See the
  [threat model](threat-model.md).

## Render

There are two Blueprints. Neither has been deployed from this repository yet, so treat the first
sync as a test and check the build logs.

| File | Layout | Cost |
|---|---|---|
| [`render.yaml`](../render.yaml) | Two free web services (`hooklens-api`, `hooklens-web`) and free Postgres. Jobs run in-process (`HOOKLENS_JOB_BACKEND=local`) | Free |
| [`render.paid.yaml`](../render.paid.yaml) | Public web, private API with a pre-deploy migration, Celery worker + beat, Foundry sim worker, Key Value, Postgres | Paid (set the Blueprint path to `render.paid.yaml`) |

### Free plan steps (`render.yaml`)

1. In the Render dashboard, choose **New → Blueprint**, connect the GitHub repository and select
   `main`.
2. Enter the `sync: false` values yourself; never commit them:
   - `hooklens-api`: `HOOKLENS_MAINNET_RPC_URL` (and optionally `HOOKLENS_SEPOLIA_RPC_URL`,
     `HOOKLENS_ETHERSCAN_API_KEY`, `HOOKLENS_ANTHROPIC_API_KEY`). Leave a key blank to disable
     that feature.
   - `hooklens-web`: `HOOKLENS_API_URL` = the API's public URL, normally
     `https://hooklens-api.onrender.com`. If Render gives the API a different URL, put that one
     here and redeploy `hooklens-web`, because the value is baked in at build time.
3. Apply. When both builds finish, open the `hooklens-web` URL and check
   `/api/v1/health/worker`.

### Free plan limits

- Free instances sleep after about 15 minutes without traffic, and the first request after that
  waits while the instance starts. A job that is running when the API instance stops is marked
  failed on the next start. Run it again.
- Free Postgres expires 30 days after creation, unless you upgrade it.
- The API has 512 MB of memory and runs one job at a time (`HOOKLENS_LOCAL_JOB_WORKERS=1`).
  Scans should fit. Foundry simulations on a mainnet fork may run out of memory or hit the
  timeout. The lab then reports an infrastructure error, which says nothing about the hook.
- Free web services cannot receive private-network traffic, so the API is public. It enforces
  workspace tokens and rate limits. The UI still proxies to it server-side.
- Migrations run on API startup (`HOOKLENS_AUTO_MIGRATE=true`), because pre-deploy commands need a
  paid plan.

### Paid layout (`render.paid.yaml`)

| Render resource | Type | Plan | Compose equivalent |
|---|---|---|---|
| `hooklens-web` | Web service (public) | `0.5c-512mb` | `frontend` |
| `hooklens-api` | Private service, `preDeployCommand: alembic upgrade head` | `0.5c-512mb` | `api` + `migrate` |
| `hooklens-worker` | Background worker, Celery `-Q default -B` | `1c-2g` | `worker` + `beat` |
| `hooklens-sim` | Background worker, Celery `-Q sim`, concurrency 1 | `2c-4g` | `sim-worker` |
| `hooklens-redis` | Key Value, `noeviction`, private only | `256mb` | `redis` |
| `hooklens-db` | Postgres 16, private only | `0.1c-256mb` | `postgres` |

The API's private `host:port` feeds the web service's `HOOKLENS_API_URL`, and `next.config.ts` adds
`http://`. Enter the RPC/Etherscan/Anthropic keys for the API and the workers when Render asks.

### Notes for both layouts

- **Submodules.** The backend build needs `contracts/lib`. It stops with a clear message if Render
  did not check out the submodules.
- **One image.** The backend Dockerfile's final stage is `sim` (app + forge), and each service picks
  its process with `dockerCommand`.
- **No shared disk.** If the API cannot find a report PDF on its own disk, it re-renders the PDF from
  the stored, hashed report content.
- **Database URL.** Render's `postgresql://` connection string is rewritten to the
  `postgresql+psycopg://` driver automatically.
- **No dev chain.** `HOOKLENS_ENABLE_LOCAL_CHAIN=false`.
- **Egress.** Render does not restrict outbound traffic by hostname. The threat-model note about
  simulation egress applies.
