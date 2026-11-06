"""ACT: custom accounting (PoolManager take/settle/mint/burn, return deltas, rounding)."""

from __future__ import annotations

from app.analyzers.context import AnalysisContext
from app.analyzers.core import Collector, ConfidenceBasis, Severity
from app.analyzers.rules.common import callback_closure

ANALYZER = "accounting"
CODE = "ACT"
PM_ACCOUNTING = ("take", "settle", "settleFor", "mint", "burn", "sync", "clear")


class AccountingAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = True

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        for cb in ctx.enabled_callbacks():
            closure = callback_closure(ctx, cb)
            ops = sorted({m for f in closure for m in f.member_names if m in PM_ACCOUNTING})
            pm_calls = [
                (f, c)
                for f in closure
                for c in f.external_calls
                if c.target_is_pool_manager and c.member in PM_ACCOUNTING
            ]
            if not ops and not pm_calls:
                continue
            divisions = sum(f.divisions for f in closure)
            evs = [ctx.ev_location(out, c.loc, f"PoolManager.{c.member} in {f.name}", f.name) for f, c in pm_calls]
            fi = ctx.index.resolve(cb) if ctx.index else None
            if fi:
                evs.insert(0, ctx.ev_function(out, fi))
            delta_flag = {
                "afterSwap": "AFTER_SWAP_RETURNS_DELTA",
                "beforeSwap": "BEFORE_SWAP_RETURNS_DELTA",
                "afterAddLiquidity": "AFTER_ADD_LIQUIDITY_RETURNS_DELTA",
                "afterRemoveLiquidity": "AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA",
            }.get(cb)
            has_delta = bool(delta_flag and ctx.enabled(delta_flag))
            sev = Severity.MEDIUM if cb == "afterRemoveLiquidity" and has_delta else Severity.LOW
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="custom_accounting",
                location=cb,
                category="accounting",
                title=f"{cb} moves currency through the PoolManager",
                severity=sev,
                severity_rationale=(
                    "The hook settles or takes currency during this callback"
                    + (" and returns a delta that the caller must pay or receive." if has_delta else ".")
                    + " This is legitimate v4 functionality; correctness is checked by the accounting scenario."
                ),
                confidence_basis=ConfidenceBasis.SOURCE_AST,
                description=(
                    f"PoolManager accounting operations used: {', '.join(ops) or 'via library'}; "
                    f"return delta flag {'enabled' if has_delta else 'not enabled'}; "
                    f"{divisions} division operation(s) in the callback path (rounding)."
                ),
                affected_functions=[cb],
                evidence_ids=evs,
                related_scenarios=["accounting_invariants"],
                lp_implications=(
                    "Amounts LPs pay or receive can differ from the pure AMM amounts."
                    if cb.endswith("Liquidity")
                    else "Swappers pay or receive amounts that differ from the pool's quote; LP fee income is unaffected "
                    "unless the delta changes swap volume through the pool."
                ),
                limitations=["Rounding direction of hook arithmetic is not evaluated statically."],
            )
