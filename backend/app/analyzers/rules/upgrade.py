"""UPG: proxies, upgrade paths, self-destruct."""

from __future__ import annotations

from app.analyzers.context import AnalysisContext
from app.analyzers.core import Collector, ConfidenceBasis, Severity
from app.services.evm import selector

ANALYZER = "upgradeability"
CODE = "UPG"
UPGRADE_SIGS = ("upgradeTo(address)", "upgradeToAndCall(address,bytes)")


class UpgradeabilityAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = False

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        r = ctx.resolved
        proxy = r.proxy
        if proxy.is_proxy:
            ev = out.evidence_item(
                "rpc_state",
                f"proxy:{ctx.address}@{ctx.block_number}",
                f"Proxy slots at block {ctx.block_number}",
                ConfidenceBasis.RPC_STATE,
                {
                    "kind": proxy.kind,
                    "implementation": proxy.implementation,
                    "admin": proxy.admin,
                    "beacon": proxy.beacon,
                    "slots": proxy.evidence,
                    "implementation_code_hash": r.implementation_code_hash,
                },
            )
            proxy_sels = set((ctx.proxy_facts or ctx.logic_facts).selectors)
            logic_sels = set(ctx.logic_facts.selectors)
            upgrade_sel = next((selector(s) for s in UPGRADE_SIGS if selector(s) in proxy_sels | logic_sels), None)
            admin_is_contract = ctx.is_contract(proxy.admin) if proxy.admin else None
            if upgrade_sel:
                ctx.facts["upgrade_selector"] = upgrade_sel
            if proxy.admin:
                ctx.facts["proxy_admin"] = proxy.admin
            if proxy.admin and admin_is_contract is False:
                sev, why = (
                    Severity.MEDIUM,
                    (
                        "A single externally owned account can replace the hook logic, including the code that runs "
                        "during liquidity removal. Permission bits stay fixed, but callback behaviour does not."
                    ),
                )
            elif proxy.admin and admin_is_contract:
                sev, why = (
                    Severity.LOW,
                    (
                        "The upgrade admin is a contract; whether it is a multisig or enforces a timelock is not established."
                    ),
                )
            else:
                sev, why = (
                    Severity.LOW,
                    "The hook logic is upgradeable; the upgrade authority could not be established.",
                )
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="upgradeable_proxy",
                location=ctx.address,
                category="upgradeability",
                title=f"Hook logic is upgradeable ({proxy.kind} proxy)",
                severity=sev,
                severity_rationale=why,
                confidence_basis=ConfidenceBasis.RPC_STATE,
                description=(
                    f"Implementation at block {ctx.block_number}: {proxy.implementation or 'unresolved'}"
                    + (f"; admin: {proxy.admin}" if proxy.admin else "")
                    + (f"; upgrade selector {upgrade_sel} present" if upgrade_sel else "")
                    + (f". {proxy.unresolved_reason}" if proxy.unresolved_reason else ".")
                ),
                evidence_ids=[ev],
                related_scenarios=["admin_upgrade", "withdrawal_failure"],
                lp_implications="Findings about the current implementation may not hold after an upgrade.",
                remediation="Use a timelocked multisig as upgrade admin, or make the hook immutable.",
                limitations=["Analysis covers the implementation at the pinned block only."],
            )
        elif ctx.index:
            ups = [f for f in ctx.index.public_functions() if f.name in ("upgradeTo", "upgradeToAndCall")]
            if ups:
                out.finding(
                    analyzer_id=ANALYZER,
                    code=CODE,
                    rule_id="uups_upgrade_function",
                    location=ctx.address,
                    category="upgradeability",
                    title="Contract exposes an upgrade function",
                    severity=Severity.LOW,
                    severity_rationale="Upgrade functions can change behaviour when used via a proxy.",
                    confidence_basis=ConfidenceBasis.SOURCE_AST,
                    description=", ".join(f.signature for f in ups),
                    evidence_ids=[ctx.ev_function(out, f) for f in ups],
                    related_scenarios=["admin_upgrade"],
                )
        if ctx.logic_facts.has_selfdestruct:
            ev = out.evidence_item(
                "bytecode_fact",
                f"selfdestruct:{ctx.address}",
                "SELFDESTRUCT opcode present",
                ConfidenceBasis.BYTECODE,
                {"opcode_counts": ctx.logic_facts.opcode_counts},
            )
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="selfdestruct_present",
                location=ctx.address,
                category="upgradeability",
                title="SELFDESTRUCT opcode present in hook code",
                severity=Severity.LOW,
                severity_rationale="Post-Cancun SELFDESTRUCT no longer deletes code outside creation transactions, "
                "but it can still move the contract's ETH balance.",
                confidence_basis=ConfidenceBasis.BYTECODE,
                description="The runtime bytecode contains SELFDESTRUCT.",
                evidence_ids=[ev],
                limitations=["Opcode presence does not establish reachability."],
            )
