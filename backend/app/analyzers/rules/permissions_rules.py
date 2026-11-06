"""PRM: hook permission bits vs. declared permissions vs. implemented callbacks."""

from __future__ import annotations

from app.analyzers.context import AnalysisContext
from app.analyzers.core import Collector, ConfidenceBasis, Severity
from app.analyzers.permissions import FLAG_EXPLANATIONS, OPERATION_FOR_CALLBACK, is_valid_hook_address, summarize
from app.analyzers.source.ast_index import _iter

ANALYZER = "permissions"
CODE = "PRM"

SCENARIOS_FOR_OPERATION = {
    "remove_liquidity": ["withdrawal_failure", "oracle_failure"],
    "add_liquidity": ["accounting_invariants"],
    "swap": ["fee_escalation", "accounting_invariants", "transaction_ordering"],
}


def declared_permissions(ctx: AnalysisContext) -> dict[str, bool] | None:
    """Parse `getHookPermissions()` from the AST: struct literal or `p.field = true` assignments."""
    if not ctx.index:
        return None
    fi = ctx.index.resolve("getHookPermissions")
    if not fi:
        return None
    node = ctx.index.nodes.get(fi.id) or {}
    declared: dict[str, bool] = {}
    for n in _iter(node.get("body")):
        if n.get("nodeType") == "FunctionCall" and n.get("kind") == "structConstructorCall":
            names = n.get("names") or []
            for name, arg in zip(names, n.get("arguments") or [], strict=False):
                if arg.get("nodeType") == "Literal" and arg.get("kind") == "bool":
                    declared[name] = arg.get("value") == "true"
        if n.get("nodeType") == "Assignment":
            lhs, rhs = n.get("leftHandSide") or {}, n.get("rightHandSide") or {}
            if lhs.get("nodeType") == "MemberAccess" and rhs.get("nodeType") == "Literal" and rhs.get("kind") == "bool":
                declared[lhs.get("memberName", "")] = rhs.get("value") == "true"
    return declared


class PermissionsAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = False

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        summary = summarize(ctx.permissions)
        ev_bits = out.evidence_item(
            "permission_bits",
            f"{ctx.address}",
            "Hook permission bits decoded from the hook address",
            ConfidenceBasis.METADATA,
            {"address": ctx.address, "derivation": "low 14 bits of the hook address (v4-core Hooks.sol)", **summary},
        )
        enabled = [p for p in ctx.permissions if p.enabled]
        ops = summary["affected_operations"]
        scenarios = sorted({s for o in ops for s in SCENARIOS_FOR_OPERATION.get(o, [])})
        out.finding(
            analyzer_id=ANALYZER,
            code=CODE,
            rule_id="enabled_callbacks",
            location=ctx.address,
            category="permissions",
            title=f"Hook callbacks execute during: {', '.join(ops) if ops else 'no pool operations'}",
            severity=Severity.INFORMATIONAL,
            severity_rationale="Permission bits describe reachable code paths, not harmful behaviour.",
            confidence_basis=ConfidenceBasis.METADATA,
            description=(
                f"The address encodes {len(enabled)} permission flag(s): "
                + (", ".join(p.flag for p in enabled) or "none")
                + ". The PoolManager will invoke the corresponding callbacks on every matching operation."
            ),
            affected_functions=summary["callbacks"],
            evidence_ids=[ev_bits],
            related_scenarios=scenarios,
            lp_implications=(
                "Hook code runs inside the listed operations; whether that code can block or alter them is "
                "examined by the other analyzers and by simulation."
            ),
            limitations=["Permissions alone do not establish whether a hook is harmful."],
        )

        valid, why = is_valid_hook_address(ctx.address, ctx.pools[0]["fee"] if ctx.pools else None)
        if not valid:
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="invalid_hook_address",
                location=ctx.address,
                category="permissions",
                title="Address bits are not a valid v4 hook configuration",
                severity=Severity.INFORMATIONAL,
                severity_rationale="An invalid configuration prevents pools from being initialised with this hook.",
                confidence_basis=ConfidenceBasis.METADATA,
                description=f"Hooks.isValidHookAddress would reject this address: {why}.",
                evidence_ids=[ev_bits],
            )

        # Implemented callbacks in the dispatcher (bytecode heuristic).
        sels = set(ctx.logic_facts.selectors)
        missing = [p for p in enabled if not p.is_return_delta and p.selector not in sels]
        if missing:
            ev = out.evidence_item(
                "bytecode_fact",
                f"dispatcher:{ctx.address}",
                "Function selectors found in the runtime dispatcher",
                ConfidenceBasis.BYTECODE,
                {"selectors": sorted(sels), "expected_missing": [p.selector for p in missing]},
            )
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="enabled_callback_missing_selector",
                location=",".join(p.callback for p in missing),
                category="permissions",
                title="Enabled callback not found in the contract dispatcher",
                severity=Severity.MEDIUM,
                severity_rationale=(
                    "If the PoolManager calls a callback the contract does not implement, the call falls through to "
                    "the fallback or reverts, which would make the affected operation fail."
                ),
                confidence_basis=ConfidenceBasis.BYTECODE,
                description=(
                    "Callbacks enabled by the address bits but whose selectors were not found: "
                    + ", ".join(f"{p.callback} ({p.selector})" for p in missing)
                ),
                affected_functions=[p.callback for p in missing],
                evidence_ids=[ev_bits, ev],
                related_scenarios=["withdrawal_failure"]
                if any(p.callback.endswith("RemoveLiquidity") for p in missing)
                else [],
                lp_implications="Operations routed through a missing callback may revert.",
                limitations=["Selector extraction from bytecode is heuristic; proxies dispatch in the implementation."],
            )

        declared = declared_permissions(ctx)
        if declared is not None:
            ev_decl = None
            fi = ctx.index.resolve("getHookPermissions") if ctx.index else None
            if fi:
                ev_decl = ctx.ev_function(out, fi, "Declared hook permissions (getHookPermissions)")
            mismatched = []
            for p in ctx.permissions:
                d = declared.get(p.field, False)
                if d != p.enabled:
                    mismatched.append(f"{p.field}: declared {d}, address bit {p.enabled}")
            if mismatched:
                out.finding(
                    analyzer_id=ANALYZER,
                    code=CODE,
                    rule_id="declared_permissions_mismatch",
                    location=ctx.address,
                    category="permissions",
                    title="Declared permissions differ from the address permission bits",
                    severity=Severity.MEDIUM,
                    severity_rationale=(
                        "The PoolManager follows the address bits, not getHookPermissions(); a mismatch means the "
                        "hook behaves differently from what its source declares."
                    ),
                    confidence_basis=ConfidenceBasis.SOURCE_AST,
                    description="; ".join(mismatched),
                    evidence_ids=[e for e in (ev_bits, ev_decl) if e],
                    limitations=["Declared permissions are parsed from literal assignments only."],
                )
            else:
                out.evidence_item(
                    "consistency_check",
                    f"perm-consistency:{ctx.address}",
                    "Declared permissions match the address bits",
                    ConfidenceBasis.SOURCE_AST,
                    {"declared": declared, "consistent": True},
                )

        for p in enabled:
            if not p.is_return_delta:
                continue
            sev, why = {
                "AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA": (
                    Severity.MEDIUM,
                    "The hook can change the token amounts an LP receives when withdrawing.",
                ),
                "AFTER_ADD_LIQUIDITY_RETURNS_DELTA": (
                    Severity.LOW,
                    "The hook can change the token amounts an LP pays when depositing.",
                ),
                "BEFORE_SWAP_RETURNS_DELTA": (
                    Severity.LOW,
                    "The hook can replace part or all of the swap with its own pricing (custom curve).",
                ),
                "AFTER_SWAP_RETURNS_DELTA": (
                    Severity.LOW,
                    "The hook can charge or credit swappers in the unspecified currency.",
                ),
            }[p.flag]
            op = OPERATION_FOR_CALLBACK[p.callback]
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id=f"return_delta_{p.flag.lower()}",
                location=ctx.address,
                category="accounting",
                title=f"Return-delta permission enabled: {p.flag}",
                severity=sev,
                severity_rationale=why + " Return deltas are legitimate v4 features; severity reflects LP exposure.",
                confidence_basis=ConfidenceBasis.METADATA,
                description=FLAG_EXPLANATIONS[p.flag],
                affected_functions=[p.callback],
                evidence_ids=[ev_bits],
                related_scenarios=["accounting_invariants"]
                + (["withdrawal_failure"] if op == "remove_liquidity" else []),
                lp_implications=why,
                remediation="Review the delta computation in the callback; HookLens accounting scenarios measure it.",
            )
