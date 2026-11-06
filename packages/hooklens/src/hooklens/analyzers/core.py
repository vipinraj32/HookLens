"""Analyzer framework: findings, evidence, severity, stable identifiers.

Analyzers are deterministic: given the same contract version and evidence they emit the same
finding IDs, severities and evidence IDs. There are no random scores or confidence percentages;
confidence is expressed as the *basis* of the claim (what kind of evidence supports it).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"
    UNKNOWN = "unknown"


SEVERITY_ORDER = {s: i for i, s in enumerate(Severity)}


class ConfidenceBasis(StrEnum):
    SOURCE_AST = "source-ast"  # established from the verified source's compiler AST
    BYTECODE = "bytecode"  # established from runtime bytecode only
    RPC_STATE = "rpc-state"  # established from on-chain state read at the pinned block
    SIMULATION = "simulation"  # observed in a fork execution
    METADATA = "metadata"  # established from explorer / compiler metadata


class FindingStatus(StrEnum):
    INFERRED = "inferred"  # static inference
    OBSERVED = "observed"  # executed and observed
    NEEDS_REVIEW = "needs-review"


def stable_id(prefix: str, *parts: str, length: int = 10) -> str:
    h = hashlib.sha1("|".join(parts).encode(), usedforsecurity=False).hexdigest()[:length]
    return f"{prefix}-{h}"


@dataclass
class EvidenceItem:
    evidence_id: str
    kind: str  # source_excerpt | bytecode_fact | permission_bits | rpc_state | metadata | simulation_step | trace
    title: str
    basis: ConfidenceBasis
    data: dict[str, Any] = field(default_factory=dict)
    source_file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    function_name: str | None = None


@dataclass
class FindingItem:
    finding_id: str
    analyzer_id: str
    rule_id: str
    category: str
    title: str
    severity: Severity
    severity_rationale: str
    confidence_basis: ConfidenceBasis
    description: str
    affected_functions: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    related_scenarios: list[str] = field(default_factory=list)
    lp_implications: str = ""
    remediation: str = ""
    limitations: list[str] = field(default_factory=list)
    status: FindingStatus = FindingStatus.INFERRED


class Collector:
    """Accumulates evidence and findings, de-duplicating by stable ID."""

    def __init__(self, scope: str = "") -> None:
        # `scope` (the hook address) makes finding IDs stable per hook, rule and location.
        self.scope = scope.lower()
        self.evidence: dict[str, EvidenceItem] = {}
        self.findings: dict[str, FindingItem] = {}

    def evidence_item(
        self,
        kind: str,
        key: str,
        title: str,
        basis: ConfidenceBasis,
        data: dict[str, Any] | None = None,
        *,
        source_file: str | None = None,
        line_start: int | None = None,
        line_end: int | None = None,
        function_name: str | None = None,
    ) -> str:
        eid = stable_id("EV", self.scope, kind, key)
        if eid not in self.evidence:
            self.evidence[eid] = EvidenceItem(
                evidence_id=eid,
                kind=kind,
                title=title,
                basis=basis,
                data=data or {},
                source_file=source_file,
                line_start=line_start,
                line_end=line_end,
                function_name=function_name,
            )
        return eid

    def finding(
        self,
        *,
        analyzer_id: str,
        code: str,
        rule_id: str,
        location: str,
        category: str,
        title: str,
        severity: Severity,
        severity_rationale: str,
        confidence_basis: ConfidenceBasis,
        description: str,
        affected_functions: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        related_scenarios: list[str] | None = None,
        lp_implications: str = "",
        remediation: str = "",
        limitations: list[str] | None = None,
        status: FindingStatus = FindingStatus.INFERRED,
    ) -> str:
        fid = stable_id(f"HL-{code}", self.scope, rule_id, location, length=8)
        missing = [e for e in (evidence_ids or []) if e not in self.evidence]
        if missing:
            raise ValueError(f"finding {fid} references unknown evidence {missing}")
        self.findings[fid] = FindingItem(
            finding_id=fid,
            analyzer_id=analyzer_id,
            rule_id=rule_id,
            category=category,
            title=title,
            severity=severity,
            severity_rationale=severity_rationale,
            confidence_basis=confidence_basis,
            description=description,
            affected_functions=sorted(set(affected_functions or [])),
            evidence_ids=list(dict.fromkeys(evidence_ids or [])),
            related_scenarios=list(dict.fromkeys(related_scenarios or [])),
            lp_implications=lp_implications,
            remediation=remediation,
            limitations=limitations or [],
            status=status,
        )
        return fid


class Analyzer(Protocol):
    analyzer_id: str
    code: str
    requires_source: bool

    def run(self, ctx: Any, out: Collector) -> None: ...
