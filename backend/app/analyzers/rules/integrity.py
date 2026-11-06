"""SRC: source integrity, i.e. correspondence between verified source and runtime bytecode;
BYT: bytecode-only heuristics used when no source is available."""

from __future__ import annotations

from app.analyzers.context import AnalysisContext
from app.analyzers.core import Collector, ConfidenceBasis, Severity

ANALYZER = "source_integrity"
CODE = "SRC"


class SourceIntegrityAnalyzer:
    analyzer_id = ANALYZER
    code = CODE
    requires_source = False

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        r = ctx.resolved
        src = r.source
        meta = ctx.logic_facts.metadata or {}
        ev = out.evidence_item(
            "metadata",
            f"source:{ctx.address}@{ctx.block_number}",
            "Source verification and compiler metadata",
            ConfidenceBasis.METADATA,
            {
                "source_status": r.source_status,
                "provider": src.bundle.provider if src.bundle else None,
                "contract_name": src.contract_name,
                "compiler_version": src.compiler_version,
                "bytecode_match": src.bytecode_match,
                "runtime_code_hash": r.runtime_code_hash,
                "implementation_code_hash": r.implementation_code_hash,
                "cbor_metadata": meta,
                "notes": src.notes,
            },
        )
        status = r.source_status
        if status in ("bytecode-only", "proxy-unresolved", "unverified"):
            out.finding(
                analyzer_id=ANALYZER,
                code=CODE,
                rule_id="source_unavailable",
                location=ctx.address,
                category="source-integrity",
                title="Verified source unavailable: analysis is bytecode-only"
                if status != "proxy-unresolved"
                else "Proxy implementation could not be resolved",
                severity=Severity.INFORMATIONAL,
                severity_rationale="Lack of source limits what can be established; it is not itself a vulnerability.",
                confidence_basis=ConfidenceBasis.METADATA,
                description="; ".join(src.notes or r.notes) or "No verified source available.",
                evidence_ids=[ev],
                limitations=[
                    "Source-based analyzers (access control, oracle, accounting, external calls) did not run."
                ],
            )
            return
        if src.bytecode_match == "mismatch":
            sev, title = Severity.MEDIUM, "Verified source does not reproduce the deployed bytecode"
            why = "Findings derived from this source may not describe the code that actually runs."
        elif src.bytecode_match in ("exact", "exact-excluding-metadata"):
            sev, title = Severity.INFORMATIONAL, "Source corresponds to the runtime bytecode"
            why = "Recompiled source matches the deployed code (immutables masked" + (
                ", metadata hash excluded)." if src.bytecode_match != "exact" else ")."
            )
        else:
            sev, title = Severity.INFORMATIONAL, "Source-to-bytecode correspondence not established"
            why = "The source could not be recompiled to compare with the deployed bytecode."
        compiler_meta = meta.get("solc")
        if compiler_meta and src.compiler_version and not str(src.compiler_version).startswith(compiler_meta):
            sev = max(sev, Severity.LOW, key=lambda s: -list(Severity).index(s))
            why += f" CBOR metadata reports solc {compiler_meta} but the explorer reports {src.compiler_version}."
        out.finding(
            analyzer_id=ANALYZER,
            code=CODE,
            rule_id=f"bytecode_match_{src.bytecode_match}",
            location=ctx.address,
            category="source-integrity",
            title=title,
            severity=sev,
            severity_rationale=why,
            confidence_basis=ConfidenceBasis.METADATA,
            description=f"Source status: {status}; provider: {src.bundle.provider if src.bundle else 'n/a'}; "
            f"contract {src.contract_name}; compiler {src.compiler_version}; match: {src.bytecode_match}.",
            evidence_ids=[ev],
            limitations=[] if src.bytecode_match.startswith("exact") else ["Correspondence could not be verified."],
        )


class BytecodeHeuristicsAnalyzer:
    analyzer_id = "bytecode_heuristics"
    code = "BYT"
    requires_source = False

    def run(self, ctx: AnalysisContext, out: Collector) -> None:
        f = ctx.logic_facts
        ev = out.evidence_item(
            "bytecode_fact",
            f"bytecode:{ctx.address}@{ctx.block_number}",
            "Runtime bytecode inventory",
            ConfidenceBasis.BYTECODE,
            f.to_dict(),
        )
        if ctx.index:
            return  # source-based analyzers supersede the heuristics
        interesting = [
            s
            for s in f.known_functions
            if s.split("(")[0]
            in (
                "owner",
                "transferOwnership",
                "pause",
                "unpause",
                "upgradeTo",
                "upgradeToAndCall",
                "setFee",
                "setLPFee",
                "setDynamicFee",
                "setMaxFee",
                "setOracle",
                "setPriceFeed",
                "grantRole",
                "rescue",
                "sweep",
                "withdraw",
                "setAllowlist",
                "setBlacklist",
            )
        ]
        if interesting:
            out.finding(
                analyzer_id=self.analyzer_id,
                code=self.code,
                rule_id="admin_selectors",
                location=ctx.address,
                category="access-control",
                title="Administrative function selectors present in bytecode",
                severity=Severity.UNKNOWN,
                severity_rationale="Selector presence shows the functions exist; their guards cannot be established without source.",
                confidence_basis=ConfidenceBasis.BYTECODE,
                description="Recognised functions: " + ", ".join(interesting),
                evidence_ids=[ev],
                related_scenarios=["admin_upgrade"],
                limitations=["Heuristic selector matching against a small signature list."],
            )
        if f.has_delegatecall and not ctx.resolved.proxy.is_proxy:
            out.finding(
                analyzer_id=self.analyzer_id,
                code=self.code,
                rule_id="delegatecall_present",
                location=ctx.address,
                category="external-calls",
                title="DELEGATECALL present in non-proxy hook code",
                severity=Severity.UNKNOWN,
                severity_rationale="Delegatecall can execute foreign code; its target and reachability are unknown.",
                confidence_basis=ConfidenceBasis.BYTECODE,
                description=f"DELEGATECALL appears {f.opcode_counts.get('DELEGATECALL', 0)} time(s).",
                evidence_ids=[ev],
            )
        if f.opcode_counts.get("CALL") or f.opcode_counts.get("STATICCALL"):
            ctx.facts["bytecode_external_targets"] = f.push20_constants
