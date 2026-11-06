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
