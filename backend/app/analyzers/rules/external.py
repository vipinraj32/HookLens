"""EXT: external calls and delegatecalls reachable from callbacks."""

from __future__ import annotations

from app.analyzers.context import AnalysisContext
from app.analyzers.core import Collector, ConfidenceBasis, Severity
from app.analyzers.rules.common import WITHDRAWAL_CALLBACKS, callback_closure
from app.analyzers.source.ast_index import TOKEN_METHODS

ANALYZER = "external_calls"
CODE = "EXT"


class ExternalCallsAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = True

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        ix = ctx.index
        assert ix is not None
        targets: list[str] = []
        for cb in ctx.enabled_callbacks():
            closure = callback_closure(ctx, cb)
            calls = [(f, c) for f in closure for c in f.external_calls if not c.target_is_pool_manager]
            asm_delegate = [f for f in closure if "delegatecall" in f.assembly_ops]
            if not calls and not asm_delegate:
                continue
            evs = []
            descs = []
            worst = Severity.INFORMATIONAL
            for f, c in calls:
                evs.append(
                    ctx.ev_location(out, c.loc, f"External call {c.target_text}.{c.member}", f.name, c.to_dict())
                )
                descs.append(f"{c.kind} `{c.target_text}.{c.member}`" + (" (in try/catch)" if c.in_try else ""))
                if c.target_state_var is not None and (sv := ix.state_var(c.target_state_var)):
                    eid = ctx.ev_state_var(out, sv)
                    evs.append(eid)
                    v = out.evidence[eid].data.get("value_at_block", {}).get("value")
                    if isinstance(v, str) and v.startswith("0x") and len(v) == 42 and v not in targets:
                        targets.append(v)
                if c.kind == "delegatecall":
                    worst = Severity.HIGH
                elif (
                    cb in WITHDRAWAL_CALLBACKS
                    and not c.in_try
                    and c.member not in TOKEN_METHODS
                    and worst != Severity.HIGH
                ):
                    worst = Severity.MEDIUM
                elif worst == Severity.INFORMATIONAL:
                    worst = Severity.LOW
            for f in asm_delegate:
                evs.append(ctx.ev_function(out, f, f"Inline assembly delegatecall in {f.name}"))
                descs.append(f"inline-assembly delegatecall in {f.name}")
                worst = Severity.HIGH
            rationale = {
                Severity.HIGH: "Delegatecall executes foreign code with the hook's storage and permissions.",
                Severity.MEDIUM: "An external dependency without failure handling runs during liquidity removal.",
                Severity.LOW: "Callback behaviour depends on external contracts.",
                Severity.INFORMATIONAL: "",
            }[worst]
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="callback_external_calls",
                location=cb,
                category="external-calls",
                title=f"{cb} makes external calls",
                severity=worst,
                severity_rationale=rationale,
                confidence_basis=ConfidenceBasis.SOURCE_AST,
                description="; ".join(descs) + ".",
                affected_functions=[cb] + sorted({f.name for f, _ in calls}),
                evidence_ids=evs,
                related_scenarios=["withdrawal_failure"] if cb in WITHDRAWAL_CALLBACKS else ["accounting_invariants"],
                lp_implications="If a dependency reverts, the operation that triggered this callback reverts.",
                remediation="Isolate external calls from liquidity removal or handle their failure.",
                limitations=["Call targets held in memory or computed at runtime are not resolved."],
            )
        if targets:
            ctx.facts["external_targets"] = targets
