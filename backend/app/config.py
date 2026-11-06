"""Application configuration.

All settings come from environment variables (or a .env file). Secrets such as RPC URLs and
API keys are kept as SecretStr so they never appear in logs, reprs or API responses.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


_DEV_WORKSPACE_SECRET = "dev-only-change-me-hooklens-workspace-secret"  # noqa: S105 - public dev default, rejected in production


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HOOKLENS_",
        env_file=(str(REPO_ROOT / ".env"), ".env"),
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # Persistence
    database_url: str = f"sqlite:///{(REPO_ROOT / 'backend' / 'hooklens.db').as_posix()}"
    redis_url: str | None = None
    auto_migrate: bool = True  # run Alembic migrations on API startup (disable when migrating separately)

    # Jobs: "local" runs jobs in an in-process thread pool (dev/tests);
    # "celery" dispatches to Celery workers through Redis (Docker/production).
    job_backend: Literal["local", "celery"] = "local"
    local_job_workers: int = 2
    job_heartbeat_timeout_s: int = 120
    scan_timeout_s: int = 600
    simulation_timeout_s: int = 900
    scenario_timeout_s: int = 300

    # Chains (server-side only; users can never supply RPC URLs)
    mainnet_rpc_url: SecretStr | None = None
    sepolia_rpc_url: SecretStr | None = None
    enable_local_chain: bool = True
    local_rpc_url: str = "http://127.0.0.1:8545"
    etherscan_api_key: SecretStr | None = None
    etherscan_api_url: str = "https://api.etherscan.io/v2/api"
    rpc_timeout_s: float = 20.0
    rpc_max_retries: int = 3
    pin_confirmations: int = 2  # default scan block = head - N on non-local chains
    log_scan_chunk_blocks: int = 50_000
    log_scan_max_chunks: int = 120

    # Foundry / simulation
    contracts_dir: Path = REPO_ROOT / "contracts"
    forge_bin: str = "forge"
    solc_cache_dir: Path | None = None
    allow_solc_download: bool = True

    # AI (optional)
    anthropic_api_key: SecretStr | None = None
    ai_model: str = "claude-opus-5-5"
    ai_timeout_s: float = 60.0

    # HTTP / security
    # NoDecode: accept the documented comma-separated form (`a,b`) instead of requiring JSON.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    workspace_secret: SecretStr = SecretStr(_DEV_WORKSPACE_SECRET)
    rate_limit_per_minute: int = 120
    rate_limit_jobs_per_minute: int = 12
    reports_dir: Path = REPO_ROOT / "backend" / "var" / "reports"

    @field_validator("mainnet_rpc_url", "sepolia_rpc_url", "etherscan_api_key", "anthropic_api_key", mode="before")
    @classmethod
    def _blank_is_unset(cls, v: object) -> object:
        # `KEY=` in a copied .env.example means "not configured", not an empty secret.
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("workspace_secret", mode="before")
    @classmethod
    def _blank_secret_is_default(cls, v: object) -> object:
        return _DEV_WORKSPACE_SECRET if isinstance(v, str) and not v.strip() else v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment == "production":
            secret = self.workspace_secret.get_secret_value()
            if secret == _DEV_WORKSPACE_SECRET or len(secret) < 32:
                raise ValueError(
                    "HOOKLENS_WORKSPACE_SECRET must be set to a random value of at least 32 characters in production."
                )
        return self

    @property
    def deployments_file(self) -> Path:
        return self.contracts_dir / "deployments" / "31337.json"

    @property
    def ai_enabled(self) -> bool:
        return self.anthropic_api_key is not None and bool(self.anthropic_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
