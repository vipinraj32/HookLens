"""WDR: what can stop or change liquidity removal."""

from __future__ import annotations

from hooklens.analyzers.context import AnalysisContext
from hooklens.analyzers.core import Collector, ConfidenceBasis, Severity
from hooklens.analyzers.rules.common import WITHDRAWAL_CALLBACKS, callback_closure, guard_of, state_writers, var_name

ANALYZER = "withdrawal"
CODE = "WDR"


class WithdrawalAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = False

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        enabled = [cb for cb in WITHDRAWAL_CALLBACKS if cb in ctx.enabled_callbacks()]
        if not enabled:
            out.evidence_item(
                "analysis_note",
                f"wdr-none:{ctx.address}",
                "No liquidity-removal callbacks enabled",
                ConfidenceBasis.METADATA,
                {
                    "note": "Permission bits are fixed by the hook address, so removal never invokes hook code, "
                    "even if the hook's logic is upgraded."
                },
            )
            return
        if not ctx.index:
            ev = out.evidence_item(
                "permission_bits",
                f"{ctx.address}",
                "Hook permission bits decoded from the hook address",
                ConfidenceBasis.METADATA,
                {},
            )
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="withdrawal_callback_unverified",
                location=",".join(enabled),
                category="withdrawal",
                title="Liquidity removal runs unverified hook code",
                severity=Severity.UNKNOWN,
                severity_rationale="Without verified source, conditions under which removal reverts cannot be established.",
                confidence_basis=ConfidenceBasis.METADATA,
                description=f"{', '.join(enabled)} execute(s) on every liquidity removal.",
                affected_functions=enabled,
                evidence_ids=[ev],
                related_scenarios=["withdrawal_failure"],
                lp_implications="Withdrawal behaviour can only be assessed by simulation.",
                limitations=["Bytecode-only analysis."],
            )
            return

        ix = ctx.index
        writers = state_writers(ctx)
        for cb in enabled:
            closure = callback_closure(ctx, cb)
            fi = ix.resolve(cb)
            evs = [ctx.ev_function(out, fi, f"{cb} implementation")] if fi else []
            conditions = []
            privileged_vars = set()
            external = [c for f in closure for c in f.external_calls if not c.target_is_pool_manager]
            for f in closure:
                for r in f.reverts:
                    refs = r.referenced_ids
                    # Skip the expected PoolManager-only caller check.
                    if r.uses_msg_sender and (
                        any(ctx.is_pool_manager_var(x) for x in refs) or "poolmanager" in r.condition.lower()
                    ):
                        continue
                    if r.kind == "revert" and not r.condition and f.name == "HookNotImplemented":
                        continue
                    state_refs = [x for x in refs if x in ix.state_vars]
                    deps = []
                    for sv in state_refs:
                        w = writers.get(sv, [])
                        priv = [x for x in w if guard_of(ctx, x)]
                        if priv:
                            privileged_vars.add(sv)
                        deps.append(f"{var_name(ctx, sv)}" + (f" (set by {', '.join(x.name for x in w)})" if w else ""))
                    tags = []
                    if r.uses_timestamp:
                        tags.append("time")
                    if r.uses_msg_sender:
                        tags.append("caller")
                    if external:
                        tags.append("external-result")
                    conditions.append(
                        {
                            "kind": r.kind,
                            "condition": r.condition,
                            "error": r.error,
                            "function": f.name,
                            "state": deps,
                            "tags": tags,
                            "line": r.loc.line_start,
                            "file": r.loc.file,
                        }
                    )
                    evs.append(
                        ctx.ev_location(
                            out,
                            r.loc,
                            f"Revert condition in {f.name}: {(r.condition or r.error or 'revert')[:80]}",
                            f.name,
                        )
                    )
            delta = ctx.enabled("AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA") and cb == "afterRemoveLiquidity"
            if not conditions and not external and not delta:
                out.evidence_item(
                    "analysis_note",
                    f"wdr-clean:{cb}",
                    f"No revert conditions found in {cb}",
                    ConfidenceBasis.SOURCE_AST,
                    {"callback": cb},
                )
                continue
            if conditions and (privileged_vars or external):
                sev = Severity.MEDIUM
                why = (
                    "Removal can revert on conditions controlled by "
                    + ("a privileged account" if privileged_vars else "")
                    + (" and " if privileged_vars and external else "")
                    + ("external contract results" if external else "")
                    + "."
                )
            elif conditions:
                sev, why = Severity.LOW, "Removal can revert on state or time conditions inside the hook."
            else:
                sev, why = (
                    Severity.LOW,
                    "Removal executes external calls or custom deltas that may fail or change amounts.",
                )
            ctx.facts.setdefault("withdrawal_conditions", []).extend(conditions)
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="withdrawal_revert_conditions",
                location=cb,
                category="withdrawal",
                title=f"{cb} can revert liquidity removal",
                severity=sev,
                severity_rationale=why + " Static analysis alone does not establish that LPs cannot withdraw.",
                confidence_basis=ConfidenceBasis.SOURCE_AST,
                description=(
                    f"{len(conditions)} revert condition(s) reachable from {cb}: "
                    + "; ".join(f"[{c['function']}] {c['condition'] or c['error'] or 'revert'}" for c in conditions[:6])
                    + (
                        f". External calls: {', '.join(c.target_text + '.' + c.member for c in external)}"
                        if external
                        else ""
                    )
                    + (
                        ". afterRemoveLiquidityReturnDelta is enabled: the hook can change removal amounts"
                        if delta
                        else ""
                    )
                    + "."
                ),
                affected_functions=[cb] + sorted({str(c["function"]) for c in conditions}),
                evidence_ids=evs,
                related_scenarios=["withdrawal_failure", "oracle_failure"] if external else ["withdrawal_failure"],
                lp_implications=(
                    "While any of these conditions holds, removing liquidity reverts and funds stay in the pool. "
                    "Whether the condition can clear without a privileged action is tested by simulation."
                ),
                remediation="Avoid blocking removals in callbacks; if a guard is required, provide an emergency exit path.",
                limitations=[
                    "Conditions are listed from revert sites; their reachability is not proven statically.",
                    "Simulation results (withdrawal_failure scenario) show which conditions actually revert.",
                ],
            )
