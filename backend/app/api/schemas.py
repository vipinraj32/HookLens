"""Request/response schemas for the public API (also the source of the OpenAPI document)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- requests


class ResolveRequest(BaseModel):
    chain_id: int = Field(examples=[31337])
    address: str = Field(min_length=42, max_length=42, examples=["0x9d536C7335f6ca4D20384AaF7F655eb364B00200"])
    block_number: int | None = Field(default=None, ge=0)


class ScanCreate(BaseModel):
    chain_id: int
    hook_address: str = Field(min_length=42, max_length=42)
    pool_id: str | None = Field(default=None, min_length=66, max_length=66)
    block_number: int | None = Field(default=None, ge=0)
    discover_pools: bool = True


ScenarioId = Literal[
    "withdrawal_failure",
    "oracle_failure",
    "fee_escalation",
    "admin_upgrade",
    "accounting_invariants",
    "transaction_ordering",
]


class SimulationCreate(BaseModel):
    pool_id: str | None = Field(default=None, min_length=66, max_length=66)
    scenarios: list[ScenarioId] | None = None
    tick_lower: int | None = Field(default=None, ge=-887272, le=887272)
    tick_upper: int | None = Field(default=None, ge=-887272, le=887272)
    amount0: str | None = Field(default=None, pattern=r"^[0-9]{1,60}$", description="Raw token0 units")
    amount1: str | None = Field(default=None, pattern=r"^[0-9]{1,60}$", description="Raw token1 units")
    liquidity: str | None = Field(default=None, pattern=r"^[0-9]{1,39}$")
    swap_amount0: str | None = Field(default=None, pattern=r"^[0-9]{1,60}$")
    swap_amount1: str | None = Field(default=None, pattern=r"^[0-9]{1,60}$")


# ---------------------------------------------------------------- responses


class JobEvent(BaseModel):
    ts: str
    stage: str
    progress: float
    message: str
    level: str
    data: dict[str, Any] | None = None


class JobOut(ORM):
    id: str
    kind: str
    subject_id: str | None
    status: str
    stage: str
    progress: float
    events: list[JobEvent]
    cancel_requested: bool
    attempts: int
    max_attempts: int
    timeout_s: int
    error: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None


class ContractOut(ORM):
    id: str
    chain_id: int
    address: str
    block_number: int
    block_hash: str
    runtime_code_hash: str
    code_size: int
    is_proxy: bool
    proxy_kind: str | None
    implementation_address: str | None
    implementation_code_hash: str | None
    proxy_admin: str | None
    source_status: str
    source_provider: str | None
    contract_name: str | None
    compiler_version: str | None
    provenance: dict[str, Any]


class ScanSummary(ORM):
    id: str
    chain_id: int
    hook_address: str
    requested_pool_id: str | None
    block_number: int | None
    status: str
    job_id: str | None
    summary: dict[str, Any]
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ScanOut(ScanSummary):
    options: dict[str, Any]
    permissions: dict[str, Any] | None
    pools: list[Any]
    analysis: dict[str, Any]
    contract: ContractOut | None


class FindingOut(ORM):
    finding_id: str
    scan_id: str
    simulation_id: str | None
    analyzer_id: str
    rule_id: str
    category: str
    title: str
    severity: str
    severity_rationale: str
    confidence_basis: str
    status: str
    description: str
    affected_functions: list[Any]
    evidence_ids: list[Any]
    related_scenarios: list[Any]
    lp_implications: str
    remediation: str
    limitations: list[Any]
    created_at: datetime
    updated_at: datetime


class EvidenceOut(ORM):
    evidence_id: str
    scan_id: str
    simulation_id: str | None
    kind: str
    title: str
    source_file: str | None
    line_start: int | None
    line_end: int | None
    function_name: str | None
    basis: str
    data: dict[str, Any]
    created_at: datetime


class ScenarioRunSummary(ORM):
    id: str
    scenario_id: str
    status: str
    status_reason: str
    parameters: dict[str, Any]
    repro_command: str
    forge_status: str | None
    duration_ms: int | None
    result_meta: dict[str, Any]
    error: dict[str, Any] | None


class ScenarioRunOut(ScenarioRunSummary):
    steps: list[Any]
    trace: dict[str, Any]


class SimulationOut(ORM):
    id: str
    scan_id: str
    job_id: str | None
    status: str
    chain_id: int
    pool_id: str | None
    fork_block: int | None
    fork_block_hash: str | None
    harness_version: str | None
    harness_commit: str | None
    spec: dict[str, Any]
    summary: dict[str, Any]
    error: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None
    runs: list[ScenarioRunSummary]


class ScenarioDefOut(BaseModel):
    scenario_id: str
    title: str
    description: str
    executes: list[str]


class Problem(BaseModel):
    type: str
    title: str
    status: int
    code: str
    detail: str
    details: dict[str, Any] = {}
    retryable: bool = False
    correlation_id: str | None = None
