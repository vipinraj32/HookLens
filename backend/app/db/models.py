"""Persistent domain model.

Identifiers, statuses, timestamps and relationships are real columns with indexes; evidence
bodies, analyzer payloads and traces are JSON(B) because their shape varies by analyzer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Contract(Base, TimestampMixin):
    """A contract identity pinned to a chain and block."""

    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("chain_id", "address", "block_number", name="uq_contract_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chain_id: Mapped[int] = mapped_column(Integer, index=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    block_number: Mapped[int] = mapped_column(Integer)
    block_hash: Mapped[str] = mapped_column(String(66))
    runtime_code_hash: Mapped[str] = mapped_column(String(66), index=True)
    code_size: Mapped[int] = mapped_column(Integer)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False)
    proxy_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    implementation_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    implementation_code_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    proxy_admin: Mapped[str | None] = mapped_column(String(42), nullable=True)
    source_status: Mapped[str] = mapped_column(String(32), index=True)
    source_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contract_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    compiler_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abi: Mapped[list[Any] | None] = mapped_column(nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Job(Base, TimestampMixin):
    """Asynchronous job state. The database row is the source of truth for progress."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_heartbeat", "status", "heartbeat_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # scan | simulation | report | explain
    subject_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="queued")
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    events: Mapped[list[Any]] = mapped_column(default=list)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    timeout_s: Mapped[int] = mapped_column(Integer, default=600)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Scan(Base, TimestampMixin):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    chain_id: Mapped[int] = mapped_column(Integer, index=True)
    hook_address: Mapped[str] = mapped_column(String(42), index=True)
    requested_pool_id: Mapped[str | None] = mapped_column(String(66), nullable=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="queued")
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id"), nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(default=dict)
    permissions: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    pools: Mapped[list[Any]] = mapped_column(default=list)
    analysis: Mapped[dict[str, Any]] = mapped_column(default=dict)  # analyzer runs, capabilities, facts
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    contract: Mapped[Contract | None] = relationship(lazy="joined")
    findings: Mapped[list[Finding]] = relationship(back_populates="scan", cascade="all, delete-orphan")


class Finding(Base, TimestampMixin):
    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("scan_id", "finding_id", name="uq_finding_per_scan"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[str | None] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    finding_id: Mapped[str] = mapped_column(String(48), index=True)  # stable, e.g. HL-WDR-3f2a9c1b
    analyzer_id: Mapped[str] = mapped_column(String(48), index=True)
    rule_id: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(256))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    severity_rationale: Mapped[str] = mapped_column(Text)
    confidence_basis: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="inferred")  # inferred | observed | needs-review
    description: Mapped[str] = mapped_column(Text)
    affected_functions: Mapped[list[Any]] = mapped_column(default=list)
    evidence_ids: Mapped[list[Any]] = mapped_column(default=list)
    related_scenarios: Mapped[list[Any]] = mapped_column(default=list)
    lp_implications: Mapped[str] = mapped_column(Text, default="")
    remediation: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[list[Any]] = mapped_column(default=list)

    scan: Mapped[Scan] = relationship(back_populates="findings")


class Evidence(Base, TimestampMixin):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("scan_id", "evidence_id", name="uq_evidence_per_scan"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[str | None] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    evidence_id: Mapped[str] = mapped_column(String(48), index=True)  # e.g. EV-5d1c0a9e2b
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(256), index=True)
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    function_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    basis: Mapped[str] = mapped_column(String(24))  # source-ast | bytecode | rpc | simulation | metadata
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Simulation(Base, TimestampMixin):
    __tablename__ = "simulations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="queued")
    chain_id: Mapped[int] = mapped_column(Integer)
    pool_id: Mapped[str | None] = mapped_column(String(66), nullable=True)
    fork_block: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fork_block_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    harness_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    harness_commit: Mapped[str | None] = mapped_column(String(128), nullable=True)  # "sha256:" + 64 hex
    spec: Mapped[dict[str, Any]] = mapped_column(default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    runs: Mapped[list[ScenarioRun]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan", order_by="ScenarioRun.created_at"
    )


class ScenarioRun(Base, TimestampMixin):
    __tablename__ = "scenario_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    repro_command: Mapped[str] = mapped_column(Text, default="")
    forge_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    steps: Mapped[list[Any]] = mapped_column(default=list)
    trace: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    simulation: Mapped[Simulation] = relationship(back_populates="runs")


class LpPosition(Base, TimestampMixin):
    __tablename__ = "lp_positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scan_id: Mapped[str | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    chain_id: Mapped[int] = mapped_column(Integer)
    pool_id: Mapped[str] = mapped_column(String(66), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    baseline: Mapped[dict[str, Any]] = mapped_column(default=dict)
    calculation_version: Mapped[str] = mapped_column(String(32))


class ExposureResult(Base, TimestampMixin):
    __tablename__ = "exposure_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    position_id: Mapped[str] = mapped_column(ForeignKey("lp_positions.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey("simulations.id", ondelete="SET NULL"), nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey("simulations.id", ondelete="SET NULL"), nullable=True)
    position_id: Mapped[str | None] = mapped_column(ForeignKey("lp_positions.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="ready")
    report_version: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)
    content_hash: Mapped[str] = mapped_column(String(128))  # "sha256:" + 64 hex
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)


class AiExplanation(Base, TimestampMixin):
    __tablename__ = "ai_explanations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey("simulations.id", ondelete="SET NULL"), nullable=True)
    finding_id: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(24))  # ready | rejected | unavailable | error
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    validation: Mapped[dict[str, Any]] = mapped_column(default=dict)


class PoolIndexEntry(Base):
    """A v4 pool that uses a hook, from the PoolManager's immutable `Initialize` event.

    The hook address is not an indexed event topic, so finding a hook's pools means reading every
    `Initialize` log. Those logs never change, so they are indexed once per chain and reused.
    """

    __tablename__ = "pool_index"
    __table_args__ = (Index("ix_pool_index_chain_hooks", "chain_id", "hooks"),)

    chain_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[str] = mapped_column(String(66), primary_key=True)
    hooks: Mapped[str] = mapped_column(String(42))  # lowercase
    currency0: Mapped[str] = mapped_column(String(42))
    currency1: Mapped[str] = mapped_column(String(42))
    fee: Mapped[int] = mapped_column(Integer)
    tick_spacing: Mapped[int] = mapped_column(Integer)
    init_sqrt_price_x96: Mapped[str] = mapped_column(String(80))
    init_tick: Mapped[int] = mapped_column(Integer)
    init_block: Mapped[int] = mapped_column(Integer, index=True)
    init_tx: Mapped[str | None] = mapped_column(String(66), nullable=True)


class PoolIndexCursor(Base):
    """How far the pool index of a chain is complete: every block in [from_block, scanned_to]."""

    __tablename__ = "pool_index_cursor"

    chain_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    pool_manager: Mapped[str] = mapped_column(String(42))
    from_block: Mapped[int] = mapped_column(Integer)
    scanned_to: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
