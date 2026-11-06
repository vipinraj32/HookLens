"""FEE: dynamic LP fee behaviour: mechanism, configuration setters and bounds."""

from __future__ import annotations

from typing import Any

from app.analyzers.context import AnalysisContext
from app.analyzers.core import Collector, ConfidenceBasis, Severity
from app.analyzers.rules.common import callback_closure, guard_of, reverts_in, state_reads, state_writers, var_name

ANALYZER = "dynamic_fee"
CODE = "FEE"
MAX_LP_FEE = 1_000_000  # LPFeeLibrary.MAX_LP_FEE (100%)


class DynamicFeeAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = False

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        dyn_pools = [p for p in ctx.pools if p.get("dynamic_fee")]
        if not ctx.index:
            if dyn_pools and ctx.enabled("BEFORE_SWAP"):
                ev = out.evidence_item(
                    "rpc_state",
                    f"dynamic-pools:{ctx.address}",
                    "Dynamic-fee pools using this hook",
                    ConfidenceBasis.RPC_STATE,
                    {"pools": [p["pool_id"] for p in dyn_pools]},
                )
                out.finding(
                    analyzer_id=ANALYZER,
                    code=CODE,
                    rule_id="dynamic_fee_unverified",
                    location=ctx.address,
                    category="fees",
                    title="Dynamic LP fee controlled by unverified code",
                    severity=Severity.UNKNOWN,
                    severity_rationale="Fee logic cannot be inspected without verified source.",
                    confidence_basis=ConfidenceBasis.RPC_STATE,
                    description="The pool uses the dynamic-fee flag and the hook has beforeSwap enabled, so the hook "
                    "can set the LP fee for each swap. The fee logic is not available for review.",
                    evidence_ids=[ev],
                    related_scenarios=["fee_escalation"],
                    lp_implications="Fees charged to traders (and earned by LPs) can change per swap.",
                    limitations=["Bytecode-only: bounds and setters could not be established."],
                )
            return

        ix = ctx.index
        before_swap = callback_closure(ctx, "beforeSwap") if ctx.enabled("BEFORE_SWAP") else []
        uses_override = any("OVERRIDE_FEE_FLAG" in f.identifiers | f.member_names for f in before_swap)
        updaters = [
            f
            for f in ix.functions.values()
            if "updateDynamicLPFee" in f.member_names
            and f.contract in {ix.contracts[c].get("name") for c in ix.linearized}
        ]
        if not uses_override and not updaters:
            return

        mechanism = []
        evs = []
        if uses_override:
            mechanism.append("beforeSwap returns an override fee (OVERRIDE_FEE_FLAG)")
            fi = ix.resolve("beforeSwap")
            if fi:
                evs.append(ctx.ev_function(out, fi, "beforeSwap fee override"))
        for f in updaters:
            mechanism.append(f"{f.name} calls poolManager.updateDynamicLPFee")
            evs.append(ctx.ev_function(out, f))

        # Fee state: variables read by beforeSwap (or by the updaters) that some function writes.
        reads = state_reads(before_swap)
        for f in updaters:
            reads |= state_reads(ix.closure(f))
        writers = state_writers(ctx)
        fee_vars = [sv for sv in reads if sv in writers and not ctx.is_pool_manager_var(sv)]
        setters = {}
        for sv in fee_vars:
            for f in writers[sv]:
                setters[f.id] = f
        bound_info: list[dict[str, Any]] = []
        adjustable_bounds = []
        for f in setters.values():
            g = guard_of(ctx, f)
            conds = [
                r for _, r in reverts_in(ix.closure(f)) if r.kind in ("if-revert", "require") and not r.uses_msg_sender
            ]
            bound_vars = sorted({rid for r in conds for rid in r.referenced_ids if rid in ix.state_vars})
            bound_info.append(
                {
                    "setter": f.signature,
                    "guard": g.to_dict() if g else None,
                    "checks": [r.condition for r in conds][:6],
                    "bound_variables": [var_name(ctx, b) for b in bound_vars],
                }
            )
            evs.append(ctx.ev_function(out, f))
            for b in bound_vars:
                if b in fee_vars:
                    continue
                for w in writers.get(b, []):
                    if w.id not in setters:
                        caps_at_protocol_max = any(
                            "MAX_LP_FEE" in x.identifiers | x.member_names or str(MAX_LP_FEE) in x.numeric_literals
                            for x in ix.closure(w)
                        )
                        adjustable_bounds.append((b, w, caps_at_protocol_max))
                        evs.append(ctx.ev_function(out, w))
        for sv in fee_vars:
            s = ix.state_var(sv)
            if s:
                evs.append(ctx.ev_state_var(out, s))

        ctx.facts["fee"] = {
            "mechanism": mechanism,
            "fee_variables": [var_name(ctx, v) for v in fee_vars],
            "setters": bound_info,
            "adjustable_bounds": [
                {"variable": var_name(ctx, b), "setter": w.signature, "capped_at_protocol_max": c}
                for b, w, c in adjustable_bounds
            ],
        }
        # Probe plan: try the protocol maximum directly, then raise each adjustable bound, then retry.
        probes = []
        for f in setters.values():
            if len(f.params) == 1 and f.params[0][1].startswith("uint"):
                probes.append(
                    {
                        "signature": f"{f.name}({f.params[0][1]})",
                        "value": MAX_LP_FEE,
                        "label": f"{f.name}_{MAX_LP_FEE}_initial",
                    }
                )
        for _b, w, _c in adjustable_bounds:
            if len(w.params) == 1 and w.params[0][1].startswith("uint"):
                probes.append(
                    {"signature": f"{w.name}({w.params[0][1]})", "value": MAX_LP_FEE, "label": f"{w.name}_{MAX_LP_FEE}"}
                )
        if adjustable_bounds:
            for f in setters.values():
                if len(f.params) == 1 and f.params[0][1].startswith("uint"):
                    probes.append(
                        {
                            "signature": f"{f.name}({f.params[0][1]})",
                            "value": MAX_LP_FEE,
                            "label": f"{f.name}_{MAX_LP_FEE}",
                        }
                    )
        ctx.facts["fee_probes"] = probes

        unguarded = [b for b in bound_info if b["guard"] is None]
        if unguarded:
            sev, why = Severity.HIGH, "Any account can change the LP fee applied to swaps."
        elif adjustable_bounds:
            sev, why = (
                Severity.MEDIUM,
                (
                    "The fee bound itself is adjustable by a privileged account"
                    + (" up to the protocol maximum of 100%" if any(c for *_, c in adjustable_bounds) else "")
                    + ", so the configured bound does not limit the fee."
                ),
            )
        elif bound_info and all(not b["checks"] for b in bound_info):
            sev, why = Severity.MEDIUM, "Fee setters perform no bound checks beyond the protocol maximum (100%)."
        else:
            sev, why = Severity.LOW, "Fees are privileged-configurable within fixed bounds."
        out.finding(
            analyzer_id=ANALYZER,
            code=CODE,
            rule_id="dynamic_fee_control",
            location=ctx.address,
            category="fees",
            title="Hook controls the LP fee applied to swaps",
            severity=sev,
            severity_rationale=why,
            confidence_basis=ConfidenceBasis.SOURCE_AST,
            description="; ".join(mechanism)
            + ". Fee state: "
            + (", ".join(ctx.facts["fee"]["fee_variables"]) or "none")
            + ". Setters: "
            + ("; ".join(f"{b['setter']} checks [{' | '.join(b['checks']) or 'none'}]" for b in bound_info) or "none")
            + ".",
            affected_functions=["beforeSwap"] + [b["setter"].split("(")[0] for b in bound_info],
            evidence_ids=evs,
            related_scenarios=["fee_escalation"],
            lp_implications=(
                "LP fee income and trader execution depend on the configured fee. Very high fees can make swaps "
                "uneconomic, reducing volume and LP fee income; fee changes are not visible in the pool key."
            ),
            remediation="Use immutable or timelocked bounds well below 100%; emit events on change.",
            limitations=["Bounds are inferred from revert conditions in setters; arithmetic is not evaluated."],
        )
