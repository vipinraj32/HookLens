"""Runs all analyzers in a fixed order with crash isolation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.analyzers.context import AnalysisContext
from app.analyzers.core import Collector
from app.analyzers.rules.access import AccessControlAnalyzer
from app.analyzers.rules.accounting import AccountingAnalyzer
from app.analyzers.rules.external import ExternalCallsAnalyzer
from app.analyzers.rules.fees import DynamicFeeAnalyzer
from app.analyzers.rules.integrity import BytecodeHeuristicsAnalyzer, SourceIntegrityAnalyzer
from app.analyzers.rules.oracle import OracleAnalyzer
from app.analyzers.rules.permissions_rules import PermissionsAnalyzer
from app.analyzers.rules.upgrade import UpgradeabilityAnalyzer
from app.analyzers.rules.withdrawal import WithdrawalAnalyzer

log = logging.getLogger(__name__)

ANALYZER_VERSION = "hooklens-analyzers/1.0.0"


def default_analyzers() -> list[Any]:
    # Order matters: access control and upgradeability publish facts used by later analyzers.
    return [
        SourceIntegrityAnalyzer(),
        PermissionsAnalyzer(),
        BytecodeHeuristicsAnalyzer(),
        AccessControlAnalyzer(),
        UpgradeabilityAnalyzer(),
        ExternalCallsAnalyzer(),
        OracleAnalyzer(),
        DynamicFeeAnalyzer(),
        WithdrawalAnalyzer(),
        AccountingAnalyzer(),
    ]


@dataclass
class AnalysisResult:
    collector: Collector
    runs: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def partial(self) -> bool:
        return any(r["status"] == "error" for r in self.runs)


def run_analyzers(ctx: AnalysisContext, analyzers: list[Any] | None = None, should_stop: Any = None) -> AnalysisResult:
    out = Collector(scope=ctx.address)
    res = AnalysisResult(collector=out, facts=ctx.facts)
    for a in analyzers or default_analyzers():
        if should_stop:
            should_stop()
        if a.requires_source and ctx.index is None:
            res.runs.append(
                {
                    "analyzer_id": a.analyzer_id,
                    "status": "skipped",
                    "reason": "requires verified source",
                    "duration_ms": 0,
                    "findings": 0,
                }
            )
            continue
        before = len(out.findings)
        t0 = time.perf_counter()
        try:
            a.run(ctx, out)
            status, reason = "completed", None
        except Exception as e:  # isolate analyzer crashes: the scan continues with partial results
            log.exception("analyzer crashed", extra={"analyzer": a.analyzer_id})
            status, reason = "error", f"{type(e).__name__}: analyzer failed; results from it are incomplete."
        res.runs.append(
            {
                "analyzer_id": a.analyzer_id,
                "status": status,
                "reason": reason,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
                "findings": len(out.findings) - before,
            }
        )
    return res
