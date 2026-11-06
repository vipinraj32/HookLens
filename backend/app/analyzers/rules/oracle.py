"""ORC: oracle dependencies in callbacks: sources, freshness, zero checks, failure handling."""

from __future__ import annotations

import re
from typing import Any

from app.analyzers.context import AnalysisContext
from app.analyzers.core import Collector, ConfidenceBasis, Severity
from app.analyzers.rules.common import WITHDRAWAL_CALLBACKS, callback_closure, guard_of, reverts_in, state_writers
from app.analyzers.source.ast_index import ORACLE_METHODS

ANALYZER = "oracle"
CODE = "ORC"
_ZERO_CHECK = re.compile(r"(<=\s*0\b|==\s*0\b|>\s*0\b|!=\s*0\b)")


def _is_oracle_call(member: str, target_type: str) -> bool:
    t = target_type.lower()
    return member in ORACLE_METHODS or any(k in t for k in ("aggregator", "oracle", "pricefeed", "feed"))


class OracleAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = True

    @staticmethod
    def _staleness(ctx: AnalysisContext, fresh: list) -> dict | None:
        """Freshness threshold used by the hook, read from the state variable in the check."""
        ix = ctx.index
        assert ix is not None
        for r in fresh:
            for rid in sorted(r.referenced_ids):
                sv = ix.state_var(rid)
                if sv is None or "int" not in sv.type_string:
                    continue
                val = ctx.state_var_value(sv)
                v = val.get("value")
                try:
                    seconds = int(v) if v is not None else None
                except (TypeError, ValueError):
                    seconds = None
                return {
                    "variable": sv.name,
                    "seconds": seconds,
                    "method": val.get("method"),
                    "condition": r.condition[:160],
                }
        return None

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        ix = ctx.index
        assert ix is not None
        deps: dict[tuple[int | None, str], dict[str, Any]] = {}
        for cb in ctx.enabled_callbacks():
            closure = callback_closure(ctx, cb)
            reverts = reverts_in(closure)
            for f in closure:
                for c in f.external_calls:
                    if c.target_is_pool_manager or not _is_oracle_call(c.member, c.target_type):
                        continue
                    key = (c.target_state_var, c.member)
                    d = deps.setdefault(key, {"call": c, "function": f, "callbacks": set(), "reverts": reverts})
                    d["callbacks"].add(cb)
        if not deps:
            return

        writers = state_writers(ctx)
        oracle_plan = None
        for (sv_id, member), d in deps.items():
            c = d["call"]
            cbs = sorted(d["callbacks"])
            evs = [ctx.ev_location(out, c.loc, f"Oracle call {c.target_text}.{member}()", d["function"].name)]
            address = None
            if sv_id is not None and (sv := ix.state_var(sv_id)):
                eid = ctx.ev_state_var(out, sv)
                evs.append(eid)
                v = out.evidence[eid].data.get("value_at_block", {}).get("value")
                if isinstance(v, str) and v.startswith("0x") and len(v) == 42:
                    address = v
            fresh = [r for _, r in d["reverts"] if r.uses_timestamp]
            zero = [r for _, r in d["reverts"] if _ZERO_CHECK.search(r.condition or "")]
            for r in (fresh + zero)[:4]:
                evs.append(ctx.ev_location(out, r.loc, f"Oracle validation: {r.condition[:80]}"))
            updaters = [f for f in writers.get(sv_id, [])] if sv_id is not None else []
            for f in updaters:
                evs.append(ctx.ev_function(out, f))
            guarded_updaters = [f for f in updaters if guard_of(ctx, f)]

            in_withdrawal = any(cb in WITHDRAWAL_CALLBACKS for cb in cbs)
            if c.in_try:
                sev, why = (
                    Severity.LOW,
                    "The oracle call is wrapped in try/catch, so a failing oracle need not revert the callback.",
                )
            elif in_withdrawal:
                sev, why = (
                    Severity.MEDIUM,
                    (
                        "An oracle call without failure handling runs during liquidity removal: if the oracle reverts, "
                        "is stale or reports invalid data (and the hook checks for it), withdrawals revert."
                    ),
                )
            else:
                sev, why = Severity.LOW, "Operations depending on this oracle revert if the oracle call fails."
            desc = (
                f"`{c.target_text}.{member}()` is called from {', '.join(cbs)}"
                + (f"; oracle address at block {ctx.block_number}: {address}" if address else "")
                + f". Freshness checks: {len(fresh)}; value checks: {len(zero)}; try/catch: {'yes' if c.in_try else 'no'}."
            )
            limitations = ["Price manipulation is not claimed: it would require establishing the oracle's mechanism."]
            if not fresh:
                limitations.append("No timestamp-based freshness check was found in the callback paths.")
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="oracle_dependency",
                location=f"{c.target_text}.{member}",
                category="oracle",
                title=f"{', '.join(cbs)} depend(s) on an external oracle",
                severity=sev,
                severity_rationale=why,
                confidence_basis=ConfidenceBasis.SOURCE_AST,
                description=desc,
                affected_functions=cbs,
                evidence_ids=evs,
                related_scenarios=["oracle_failure"] + (["withdrawal_failure"] if in_withdrawal else []),
                lp_implications=(
                    "LP withdrawals may depend on the oracle's availability and freshness."
                    if in_withdrawal
                    else "Swaps or deposits may depend on the oracle's availability."
                ),
                remediation="Handle oracle failure without blocking liquidity removal (try/catch with a safe fallback).",
                limitations=limitations,
            )
            if updaters:
                out.finding(
                    analyzer_id=ANALYZER,
                    code=CODE,
                    rule_id="oracle_replaceable",
                    location=f"{c.target_text}",
                    category="oracle",
                    title="Oracle address can be replaced",
                    severity=Severity.LOW if guarded_updaters else Severity.HIGH,
                    severity_rationale=(
                        "A privileged account can point the hook at a different price source."
                        if guarded_updaters
                        else "Any account can replace the oracle used by callbacks."
                    ),
                    confidence_basis=ConfidenceBasis.SOURCE_AST,
                    description="Functions writing the oracle reference: " + ", ".join(f.signature for f in updaters),
                    affected_functions=[f.name for f in updaters],
                    evidence_ids=evs,
                    related_scenarios=["oracle_failure", "admin_upgrade"],
                )
            if oracle_plan is None and address:
                kind = "chainlink" if member == "latestRoundData" else "uint"
                sel = c.function_selector or ("0xfeaf968c" if member == "latestRoundData" else None)
                if sel:
                    oracle_plan = {
                        "address": address,
                        "selector": sel,
                        "kind": kind,
                        "member": member,
                        "callbacks": cbs,
                        "staleness": self._staleness(ctx, fresh),
                    }
        if oracle_plan:
            ctx.facts["oracle"] = oracle_plan
