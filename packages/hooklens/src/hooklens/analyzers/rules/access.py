"""ACC: access control, privileged configuration, pause mechanisms."""

from __future__ import annotations

from hooklens.analyzers.context import AnalysisContext
from hooklens.analyzers.core import Collector, ConfidenceBasis, Severity
from hooklens.analyzers.rules.common import (
    ROLE_NAMES,
    WITHDRAWAL_CALLBACKS,
    callback_closure,
    encode_probe_args,
    guard_of,
    is_callback,
    state_reads,
    state_writers,
    var_name,
)
from hooklens.evm import selector

ANALYZER = "access_control"
CODE = "ACC"


class AccessControlAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = True

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        ix = ctx.index
        assert ix is not None
        privileged = []
        for fi in ix.public_functions():
            if fi.mutability in ("view", "pure") or is_callback(fi.name):
                continue
            g = guard_of(ctx, fi)
            if g and g.privileged:
                privileged.append(g)
        ctx.facts["privileged_functions"] = [g.to_dict() for g in privileged]

        # Owner-like variables: referenced by sender checks, or named like roles.
        role_vars = {}
        for g in privileged:
            for v in g.variables:
                role_vars[v] = True
        for sv in ix.state_vars.values():
            if sv.type_string.startswith("address") and sv.name.lower().strip("_") in ROLE_NAMES:
                role_vars.setdefault(sv.name, True)
        owner_evidence = []
        # (rank, name, value): several role variables can coexist (e.g. Ownable `_owner` next to a
        # `factory` that is also allowed to call some functions). Rank owner-named variables first,
        # then other role names, then the variable referenced by the most access checks.
        guard_uses = {v: sum(v in g.variables for g in privileged) for v in role_vars}
        candidates: list[tuple[tuple[int, int, int], str, str]] = []
        for order, sv in enumerate(ix.state_vars.values()):
            if sv.name in role_vars:
                eid = ctx.ev_state_var(out, sv)
                owner_evidence.append(eid)
                val = out.evidence[eid].data.get("value_at_block", {}).get("value")
                if isinstance(val, str) and val.startswith("0x") and len(val) == 42:
                    base = sv.name.lower().strip("_")
                    name_rank = 0 if base == "owner" else 1 if base in ROLE_NAMES else 2
                    candidates.append(((name_rank, -guard_uses.get(sv.name, 0), order), sv.name, val))
        owner_value = None
        getter = _owner_getter(ctx)
        if getter:
            owner_value = getter
            ctx.facts["owner"] = getter
            ctx.facts["owner_variable"] = "owner()"
        elif candidates:
            _, name, owner_value = min(candidates)
            ctx.facts["owner"] = owner_value
            ctx.facts["owner_variable"] = name
        if owner_value:
            is_c = ctx.is_contract(owner_value)
            ctx.facts["owner_is_contract"] = is_c

        if not privileged:
            out.evidence_item(
                "analysis_note",
                f"acc-none:{ctx.address}",
                "No caller-restricted state-changing functions",
                ConfidenceBasis.SOURCE_AST,
                {"note": "No msg.sender checks or access modifiers found."},
            )
            return

        ev_funcs = [ctx.ev_function(out, g.function) for g in privileged]
        owner_note = ""
        if owner_value:
            kind = {
                True: "a contract (e.g. multisig or timelock; not established)",
                False: "an externally owned account",
                None: "of unknown type",
            }[ctx.facts.get("owner_is_contract")]
            owner_note = (
                f" The current {ctx.facts.get('owner_variable')} at block {ctx.block_number} is {owner_value}, {kind}."
            )
        out.finding(
            analyzer_id=ANALYZER,
            code=CODE,
            rule_id="privileged_functions",
            location=ctx.address,
            category="access-control",
            title=f"{len(privileged)} privileged function(s) restricted to specific callers",
            severity=Severity.INFORMATIONAL,
            severity_rationale="Administrative functions are common and not malicious by themselves.",
            confidence_basis=ConfidenceBasis.SOURCE_AST,
            description="Caller-restricted functions: "
            + ", ".join(g.function.signature for g in privileged)
            + "."
            + owner_note,
            affected_functions=[g.function.name for g in privileged],
            evidence_ids=ev_funcs + owner_evidence,
            related_scenarios=["admin_upgrade"],
            lp_implications="Privileged accounts can change hook configuration; see related findings for what it controls.",
        )

        # Which privileged writes are read by callbacks?
        writers = state_writers(ctx)
        priv_ids = {g.function.id for g in privileged}
        cb_reads: dict[str, set[int]] = {cb: state_reads(callback_closure(ctx, cb)) for cb in ctx.enabled_callbacks()}
        for cb, reads in cb_reads.items():
            controlled = []
            for sv_id in sorted(reads):
                fns = [f for f in writers.get(sv_id, []) if f.id in priv_ids]
                if fns:
                    controlled.append((sv_id, fns))
            if not controlled:
                continue
            withdrawal = cb in WITHDRAWAL_CALLBACKS
            sev = Severity.MEDIUM if withdrawal else Severity.LOW
            evs = [ctx.ev_function(out, fn)] if (fn := ix.resolve(cb)) else []
            for _sv, fns in controlled:
                evs += [ctx.ev_function(out, f) for f in fns]
            desc = "; ".join(
                f"`{var_name(ctx, sv)}` is read by {cb} and written by {', '.join(f.name for f in fns)}"
                for sv, fns in controlled
            )
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="privileged_state_in_callback",
                location=cb,
                category="access-control",
                title=f"Privileged configuration influences {cb}",
                severity=sev,
                severity_rationale=(
                    (
                        "State read during liquidity removal is changeable by a privileged account, so that account can "
                        "influence whether or how LPs withdraw."
                        if withdrawal
                        else "Privileged accounts can change state that this callback depends on."
                    )
                    + " Static analysis does not establish that this is abused."
                ),
                confidence_basis=ConfidenceBasis.SOURCE_AST,
                description=desc + ".",
                affected_functions=[cb] + sorted({f.name for _, fns in controlled for f in fns}),
                evidence_ids=evs,
                related_scenarios=["withdrawal_failure", "admin_upgrade"]
                if withdrawal
                else ["admin_upgrade", "fee_escalation"],
                lp_implications=(
                    "A privileged account may be able to block or condition withdrawals."
                    if withdrawal
                    else "A privileged account may change swap-time behaviour (e.g. fees) that affects LP economics."
                ),
                remediation="Bound privileged parameters, add timelocks, and ensure withdrawals cannot be disabled.",
                limitations=["Whether the configuration change is harmful depends on values; see simulations."],
            )

        # Pause mechanisms
        pause_fns = [g.function for g in privileged if g.function.name.lower() in ("pause", "setpaused", "pauseall")]
        pause_vars = [sv for sv in ix.state_vars.values() if "pause" in sv.name.lower() and sv.type_string == "bool"]
        if pause_fns or pause_vars:
            reads_withdraw = any(sv.id in cb_reads.get(cb, set()) for sv in pause_vars for cb in WITHDRAWAL_CALLBACKS)
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="pause_mechanism",
                location=ctx.address,
                category="access-control",
                title="Pause mechanism " + ("gates liquidity removal" if reads_withdraw else "present"),
                severity=Severity.MEDIUM if reads_withdraw else Severity.LOW,
                severity_rationale=(
                    "A pause flag checked during liquidity removal lets its controller stop withdrawals."
                    if reads_withdraw
                    else "Pausing can halt pool operations that read the flag."
                ),
                confidence_basis=ConfidenceBasis.SOURCE_AST,
                description="Pause functions: "
                + (", ".join(f.signature for f in pause_fns) or "none found")
                + "; pause state: "
                + (", ".join(v.name for v in pause_vars) or "none"),
                affected_functions=[f.name for f in pause_fns],
                evidence_ids=[ctx.ev_function(out, f) for f in pause_fns]
                + [ctx.ev_state_var(out, v) for v in pause_vars],
                related_scenarios=["withdrawal_failure"],
                lp_implications="While paused, affected operations revert; recovery depends on the controller.",
                remediation="Exempt liquidity removal from pausing, or bound the pause duration.",
            )
            if pause_fns:
                ctx.facts["pause_call"] = selector(pause_fns[0].signature.replace("struct ", ""))

        # tx.origin
        for g in privileged:
            if any(f.uses_tx_origin for f in ix.closure(g.function)):
                out.finding(
                    analyzer_id=ANALYZER,
                    code=CODE,
                    rule_id="tx_origin_auth",
                    location=g.function.name,
                    category="access-control",
                    title="tx.origin used in an access-controlled path",
                    severity=Severity.LOW,
                    severity_rationale="tx.origin authorisation can be phished through intermediate contracts.",
                    confidence_basis=ConfidenceBasis.SOURCE_AST,
                    description=f"{g.function.signature} reads tx.origin.",
                    affected_functions=[g.function.name],
                    evidence_ids=[ctx.ev_function(out, g.function)],
                )

        # Admin-call plan for simulation: benign arguments, excluding upgrades (handled separately).
        calls = []
        for g in privileged:
            fi = g.function
            if fi.name.lower().startswith("upgrade"):
                continue
            enc = encode_probe_args(fi.params)
            if enc is None:
                continue
            calls.append({"signature": _abi_sig(fi.name, enc[0]), "types": enc[0], "label": fi.name})
        ctx.facts["admin_calls"] = calls[:8]


def _abi_sig(name: str, types: list[str]) -> str:
    return f"{name}({','.join(types)})"


def _owner_getter(ctx: AnalysisContext) -> str | None:
    """`owner()` at the pinned block, when the verified source exposes it (e.g. OpenZeppelin Ownable)."""
    ix = ctx.index
    if ix is None or ctx.rpc_call is None:
        return None
    if not any(f.name == "owner" and not f.params for f in ix.public_functions()):
        return None
    out = ctx.rpc_call(ctx.address, "0x8da5cb5b")  # owner()
    if not out or len(out) < 66:
        return None
    word = int(out[2:66], 16)
    if word == 0 or word >> 160:
        return None
    from eth_utils import to_checksum_address

    return to_checksum_address(f"0x{word:040x}")
