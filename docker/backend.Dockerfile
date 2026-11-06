# syntax=docker/dockerfile:1.7
#
# HookLens backend images. Build context: repository root (needs backend/, packages/hooklens/ and contracts/).
#   docker build -f docker/backend.Dockerfile --target app .   # API + default Celery worker
#   docker build -f docker/backend.Dockerfile --target sim .   # Foundry simulation worker
#
# contracts/lib comes from the git submodules when they are checked out. Hosts that do not check
# out submodules recursively (e.g. Render) get the same pinned commits fetched during the build.
# The pins below must equal `git ls-files -s contracts/lib` (backend/tests/test_deploy_config.py).

ARG PYTHON_VERSION=3.12
ARG FOUNDRY_VERSION=v1.9.0
ARG FORGE_STD_REV=dc647cc030d9d65910d8f1172a0cde48d7106e32
ARG V4_PERIPHERY_REV=c6e4754dab11bd38c6f08ac51c3c868569e93d64

# ---------------------------------------------------------------- Foundry toolchain
FROM debian:bookworm-slim AS foundry
ARG FOUNDRY_VERSION
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/*
ENV FOUNDRY_DIR=/opt/foundry
RUN curl -fsSL https://foundry.paradigm.xyz | bash \
 && /opt/foundry/bin/foundryup --install "${FOUNDRY_VERSION}" \
 && /opt/foundry/bin/forge --version

# ---------------------------------------------------------------- compiled contracts
FROM foundry AS contracts
ARG FORGE_STD_REV
ARG V4_PERIPHERY_REV
WORKDIR /build/contracts
COPY contracts/ ./
# Fetch the pinned submodules (recursively) when the build context does not contain them.
RUN set -eu; \
    if [ ! -f lib/v4-periphery/lib/v4-core/src/libraries/Hooks.sol ] || [ ! -f lib/forge-std/src/Test.sol ]; then \
      echo "contracts/lib not checked out: fetching pinned submodules"; \
      rm -rf lib/forge-std lib/v4-periphery; \
      fetch() { \
        git clone --quiet --filter=blob:none "$1" "$2"; \
        git -C "$2" -c advice.detachedHead=false checkout --quiet "$3"; \
        git -C "$2" submodule update --init --recursive --depth 1 --quiet; \
        rm -rf "$2/.git"; \
      }; \
      fetch https://github.com/foundry-rs/forge-std lib/forge-std "${FORGE_STD_REV}"; \
      fetch https://github.com/Uniswap/v4-periphery lib/v4-periphery "${V4_PERIPHERY_REV}"; \
    fi; \
    test -f lib/v4-periphery/lib/v4-core/src/libraries/Hooks.sol
# Compile once at image build time so workers never need to download solc at runtime.
RUN mkdir -p /root/.svm \
 && /opt/foundry/bin/forge build \
 && rm -rf sim-out/runs broadcast

# ---------------------------------------------------------------- Python dependencies
FROM python:${PYTHON_VERSION}-slim AS pydeps
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# The analysis engine is the `hooklens` package (a path dependency of the backend, shared with the CLI).
COPY packages/hooklens/ /app/packages/hooklens/
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev \
 && rm -rf hooklens.db* var tests

# ---------------------------------------------------------------- API / default worker
FROM python:${PYTHON_VERSION}-slim AS app
RUN groupadd --system --gid 10001 hooklens \
 && useradd --system --uid 10001 --gid hooklens --home-dir /app --shell /usr/sbin/nologin hooklens
WORKDIR /app/backend
COPY --from=pydeps --chown=hooklens:hooklens /app/packages /app/packages
COPY --from=pydeps --chown=hooklens:hooklens /app/backend /app/backend
# Artifacts are used to decode reverts and to match Anvil fixture bytecode to source.
COPY --from=contracts --chown=hooklens:hooklens /build/contracts /app/contracts
RUN mkdir -p /app/backend/var/reports /app/contracts/deployments /app/contracts/sim-out/runs \
 && chown -R hooklens:hooklens /app/backend/var /app/contracts/deployments /app/contracts/sim-out
ENV PATH="/app/backend/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    HOOKLENS_ENVIRONMENT=production \
    HOOKLENS_CONTRACTS_DIR=/app/contracts \
    HOOKLENS_REPORTS_DIR=/app/backend/var/reports
USER hooklens
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

# ---------------------------------------------------------------- simulation worker
FROM app AS sim
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git \
 && rm -rf /var/lib/apt/lists/*
COPY --from=foundry /opt/foundry/bin/forge /opt/foundry/bin/anvil /opt/foundry/bin/cast /usr/local/bin/
# svm-rs uses ~/.svm when that directory exists (created before the build above), so the solc
# that compiled the project ships with the image and nothing is downloaded at runtime.
COPY --from=contracts --chown=hooklens:hooklens /root/.svm /app/.svm
RUN mkdir -p /app/.foundry && chown -R hooklens:hooklens /app/contracts /app/.foundry
ENV FOUNDRY_FFI=false HOME=/app
USER hooklens
HEALTHCHECK NONE
CMD ["celery", "-A", "app.worker.celery_app", "worker", "-Q", "sim", "--concurrency=1", "--loglevel=INFO"]
