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

[`render.yaml`](../render.yaml) is a Render Blueprint for the same topology. It has **not** been
deployed from this repository yet, so treat the first Blueprint sync as a test and check the
build logs.

| Render resource | Type | Plan in the Blueprint | Compose equivalent |
|---|---|---|---|
| `hooklens-web` | Web service (public) | `0.5c-512mb` | `frontend` |
| `hooklens-api` | Private service, `preDeployCommand: alembic upgrade head` | `0.5c-512mb` | `api` + `migrate` |
| `hooklens-worker` | Background worker, Celery `-Q default -B` | `1c-2g` | `worker` + `beat` |
| `hooklens-sim` | Background worker, Celery `-Q sim`, concurrency 1 | `2c-4g` | `sim-worker` |
| `hooklens-redis` | Key Value, `noeviction`, private only | `256mb` | `redis` |
| `hooklens-db` | Postgres 16, private only | `0.1c-256mb` | `postgres` |

### Steps

1. Push the repository to GitHub (or GitLab) with the submodules committed as submodule
   references. The backend build fails early with a clear message if `contracts/lib` was not
   checked out.
2. In the Render dashboard, choose **New → Blueprint**, connect the repository and select `main`.
3. Render asks for the `sync: false` values for each backend service. Enter them in the dashboard;
   never commit them:
   - `HOOKLENS_MAINNET_RPC_URL` / `HOOKLENS_SEPOLIA_RPC_URL` (API, worker and sim worker). Leave
     a chain blank to disable it.
   - `HOOKLENS_ETHERSCAN_API_KEY` and `HOOKLENS_ANTHROPIC_API_KEY` (API and worker), both
     optional.
4. Apply the Blueprint. Open the `hooklens-web` URL, then check `/api/v1/health/worker`. It should
   report Celery reachable, forge available, and the chains you configured.

### Notes

- **Cost.** Private services and background workers have no free plan on Render, and the
  pre-deploy command needs a paid plan, so this Blueprint is a paid deployment. Check
  Render's pricing before applying, and lower the plans if you need to. The sim worker needs
  enough memory for `forge` on a mainnet fork.
- **Private API.** Only `hooklens-web` is public. Its `HOOKLENS_API_URL` comes from the
  API's private `host:port`. `next.config.ts` adds `http://`, and the value is used at build
  time (Render passes environment variables as Docker build args).
- **One image, three processes.** The backend Dockerfile's final stage is `sim`, so the API and
  both workers build it and select their process with `dockerCommand`.
- **No shared disk.** Report PDFs are rendered by the worker. If the API cannot find the file on
  its own disk, it re-renders the PDF from the stored, hashed report content. Simulation run
  outputs are read by the sim worker that wrote them.
- **Database URL.** Render's `postgresql://` connection string is rewritten to the
  `postgresql+psycopg://` driver automatically.
- **No dev chain.** `HOOKLENS_ENABLE_LOCAL_CHAIN=false`. The Anvil fixtures are a local-only
  profile.
- **Egress.** Render does not restrict outbound traffic by hostname. The threat-model note
  about `sim-worker` egress applies.
