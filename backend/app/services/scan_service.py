"""Scan orchestration: resolution -> permissions -> source -> pools -> analyzers -> persistence."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chains import get_chain
from app.config import get_settings
from app.db.base import session_scope
from app.db.models import Contract, Evidence, Finding, Scan, utcnow
from app.errors import AppError, RpcNotConfigured
from app.jobs.dispatch import get_dispatcher
from app.jobs.manager import JobContext, create_job, on_terminal, register
from app.services.evm import validate_address, validate_pool_id
from app.services.pool_index import discover_with_index
from app.services.pools import discover_pools, read_pool_state, token_metadata
from app.services.resolver import resolve_contract
from app.services.rpc import RpcClient
from hooklens.analyzers.bytecode import analyze_bytecode
from hooklens.analyzers.context import AnalysisContext
from hooklens.analyzers.core import SEVERITY_ORDER, Collector, Severity
from hooklens.analyzers.permissions import decode, summarize
from hooklens.analyzers.runner import ANALYZER_VERSION, run_analyzers
from hooklens.analyzers.source.ast_index import AstIndex

log = logging.getLogger(__name__)


def create_scan(
    db: Session,
    *,
    workspace_id: str,
    chain_id: int,
    hook_address: str,
    pool_id: str | None,
    block_number: int | None,
    options: dict[str, Any],
) -> Scan:
    chain = get_chain(chain_id)
    address = validate_address(hook_address, field="hook_address")
    pid = validate_pool_id(pool_id) if pool_id else None
    if block_number is not None and block_number < 0:
        raise AppError("invalid_block", "block_number must be non-negative.", status_code=422)
    if not chain.rpc_configured:
        raise RpcNotConfigured(chain_id)
    if not chain.pool_manager:
        raise AppError(
            "pool_manager_unavailable",
            f"No Uniswap v4 PoolManager is known for chain {chain_id}"
            + (" (local fixtures not deployed: run scripts/dev-chain.sh)." if chain.is_local else "."),
            status_code=503,
        )
    scan = Scan(
        workspace_id=workspace_id,
        chain_id=chain_id,
        hook_address=address,
        requested_pool_id=pid,
        block_number=block_number,
        status="queued",
        options=options,
    )
    db.add(scan)
    db.flush()
    job = create_job(
        db,
        kind="scan",
        workspace_id=workspace_id,
        subject_id=scan.id,
        payload={"scan_id": scan.id},
        timeout_s=get_settings().scan_timeout_s,
    )
    scan.job_id = job.id
    db.commit()
    get_dispatcher().dispatch(job.id)
    return scan


@on_terminal("scan")
def _scan_terminal(payload: dict[str, Any], status: str, error: dict[str, Any] | None) -> None:
    with session_scope() as db:
        scan = db.get(Scan, payload.get("scan_id"))
        if scan and scan.status not in ("completed", "partial"):
            scan.status = status
            scan.error = error


@register("scan")
def run_scan_job(jc: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    scan_id = payload["scan_id"]
    with session_scope() as db:
        scan = db.get(Scan, scan_id)
        if scan is None:
            raise AppError("not_found", "Scan disappeared before it could run.", status_code=404)
        scan.status = "running"
        chain_id, address, block, pool_id = scan.chain_id, scan.hook_address, scan.block_number, scan.requested_pool_id
        options = dict(scan.options or {})
    chain = get_chain(chain_id)

    jc.update("resolving", 0.05, f"Resolving {address} on {chain.name}")
    with RpcClient(chain) as rpc:
        resolved = resolve_contract(rpc, chain, address, block)
        block = resolved.block_number
        jc.update(
            "resolving",
            0.15,
            f"Pinned block {block}; runtime code {resolved.runtime_code_hash[:12]}…",
            data={"block": block, "code_hash": resolved.runtime_code_hash},
        )
        if resolved.proxy.is_proxy:
            jc.update(
                "resolving",
                0.18,
                f"Proxy detected ({resolved.proxy.kind}); implementation "
                f"{resolved.proxy.implementation or 'unresolved'}",
            )

        perms = decode(resolved.address)
        perm_summary = summarize(perms)
        jc.update("permissions", 0.25, "Decoded permissions: " + (", ".join(perm_summary["enabled_flags"]) or "none"))

        jc.update("source", 0.3, f"Source status: {resolved.source_status}")
        index = None
        if resolved.source.bundle is not None:
            try:
                index = AstIndex(resolved.source.bundle)
                if index.main is None:
                    index = None
                    resolved.notes.append("Contract definition not found in the source AST.")
            except Exception:
                log.exception("AST indexing failed")
                index = None
                resolved.notes.append("AST indexing failed; source-based analyzers are skipped.")
        jc.check()

        pools: list[dict[str, Any]] = []
        discovery: dict[str, Any] = {"status": "skipped"}
        if options.get("discover_pools", True):
            jc.update("pools", 0.4, "Searching PoolManager Initialize events for pools using this hook")
            if pool_id or chain.is_local:
                # A pool id is a direct indexed-topic query; local dev chains can be reset, so never cached.
                res = discover_pools(
                    rpc, chain, resolved.address, block, pool_id=pool_id, should_stop=jc.cancel_requested
                )
            else:
                res = discover_with_index(rpc, chain, resolved.address, block, should_stop=jc.cancel_requested)
            jc.check()
            discovery = res.to_dict()
            for p in res.pools[:20]:
                d = p.to_dict()
                try:
                    d["state"] = read_pool_state(rpc, chain.pool_manager or "", p.pool_id, block)
                    d["token0"] = token_metadata(rpc, p.currency0, block)
                    d["token1"] = token_metadata(rpc, p.currency1, block)
                except AppError as e:
                    d["state_error"] = e.to_dict()
                pools.append(d)
            jc.update("pools", 0.5, f"Found {len(pools)} pool(s); discovery {discovery['status']}")

        jc.update("analyzing", 0.55, "Running deterministic analyzers")
        ctx = AnalysisContext(
            chain_id=chain_id,
            address=resolved.address,
            block_number=block,
            pool_manager=chain.pool_manager,
            permissions=perms,
            logic_facts=analyze_bytecode(resolved.logic_code),
            proxy_facts=analyze_bytecode(resolved.runtime_code) if resolved.proxy.is_proxy else None,
            resolved=resolved,
            index=index,
            proxy_index=None,
            pools=pools,
            rpc_call=lambda to, data: rpc.try_call(to, data, block),
            rpc_storage=lambda a, s: rpc.get_storage_at(a, s, block),
            rpc_code=lambda a: rpc.get_code(a, block),
        )
        result = run_analyzers(ctx, should_stop=jc.check)
    jc.update(
        "persisting",
        0.9,
        f"{len(result.collector.findings)} finding(s), {len(result.collector.evidence)} evidence item(s)",
    )

    partial = result.partial or discovery.get("status") in ("partial", "failed")
    with session_scope() as db:
        contract = db.execute(
            select(Contract).where(
                Contract.chain_id == chain_id, Contract.address == resolved.address, Contract.block_number == block
            )
        ).scalar_one_or_none()
        if contract is None:
            contract = Contract(chain_id=chain_id, address=resolved.address, block_number=block)
            db.add(contract)
        contract.block_hash = resolved.block_hash
        contract.runtime_code_hash = resolved.runtime_code_hash
        contract.code_size = len(resolved.runtime_code)
        contract.is_proxy = resolved.proxy.is_proxy
        contract.proxy_kind = resolved.proxy.kind
        contract.implementation_address = resolved.proxy.implementation
        contract.implementation_code_hash = resolved.implementation_code_hash
        contract.proxy_admin = resolved.proxy.admin
        contract.source_status = resolved.source_status
        contract.source_provider = resolved.source.bundle.provider if resolved.source.bundle else None
        contract.contract_name = resolved.source.contract_name
        contract.compiler_version = resolved.source.compiler_version
        contract.abi = resolved.source.abi
        contract.provenance = resolved.provenance()
        db.flush()

        scan = db.get(Scan, scan_id)
        assert scan is not None
        scan.contract_id = contract.id
        scan.block_number = block
        scan.permissions = perm_summary
        scan.pools = pools
        scan.analysis = {
            "analyzer_version": ANALYZER_VERSION,
            "runs": result.runs,
            "facts": _jsonable(result.facts),
            "bytecode": ctx.logic_facts.to_dict(),
            "proxy_bytecode": ctx.proxy_facts.to_dict() if ctx.proxy_facts else None,
            "discovery": discovery,
            "source": resolved.source.bundle.summary() if resolved.source.bundle else None,
            "capabilities": capabilities(index is not None, resolved.source_status),
            "provenance": resolved.provenance(),
        }
        _persist_collector(db, scan, result.collector, simulation_id=None)
        scan.summary = summarize_findings(result.collector)
        scan.status = "partial" if partial else "completed"
        scan.error = None
        scan.updated_at = utcnow()
    return {"message": f"Scan {'partially ' if partial else ''}completed", "scan_id": scan_id, "partial": partial}


def capabilities(has_source: bool, source_status: str) -> dict[str, Any]:
    return {
        "permission_decoding": True,
        "bytecode_analysis": True,
        "source_analysis": has_source,
        "source_status": source_status,
        "unavailable": []
        if has_source
        else [
            "access-control analysis",
            "oracle dependency analysis",
            "external-call analysis",
            "accounting analysis",
            "source excerpts",
        ],
    }


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    if isinstance(v, bytes):
        return "0x" + v.hex()
    return v


def _persist_collector(db: Session, scan: Scan, out: Collector, simulation_id: str | None) -> None:
    existing_ev = {
        e.evidence_id for e in db.execute(select(Evidence).where(Evidence.scan_id == scan.id)).scalars().all()
    }
    for e in out.evidence.values():
        if e.evidence_id in existing_ev:
            continue
        db.add(
            Evidence(
                scan_id=scan.id,
                simulation_id=simulation_id,
                evidence_id=e.evidence_id,
                kind=e.kind,
                title=e.title[:256],
                source_file=e.source_file,
                line_start=e.line_start,
                line_end=e.line_end,
                function_name=e.function_name,
                basis=e.basis.value,
                data=_jsonable(e.data),
            )
        )
    existing_f = {
        f.finding_id: f for f in db.execute(select(Finding).where(Finding.scan_id == scan.id)).scalars().all()
    }
    for f in out.findings.values():
        row = existing_f.get(f.finding_id)
        merge_from: list[Any] = []
        merge_scen: list[Any] = []
        if row is None:
            row = Finding(scan_id=scan.id, finding_id=f.finding_id)
            db.add(row)
            existing_f[f.finding_id] = row
        elif simulation_id is not None and row.simulation_id == simulation_id:
            # Same observation from another scenario of the same simulation: merge evidence.
            merge_from, merge_scen = list(row.evidence_ids or []), list(row.related_scenarios or [])
        row.simulation_id = simulation_id
        row.analyzer_id = f.analyzer_id
        row.rule_id = f.rule_id
        row.category = f.category
        row.title = f.title[:256]
        row.severity = f.severity.value
        row.severity_rationale = f.severity_rationale
        row.confidence_basis = f.confidence_basis.value
        row.status = f.status.value
        row.description = f.description
        row.affected_functions = f.affected_functions
        row.evidence_ids = list(dict.fromkeys(merge_from + f.evidence_ids))
        row.related_scenarios = list(dict.fromkeys(merge_scen + f.related_scenarios))
        row.lp_implications = f.lp_implications
        row.remediation = f.remediation
        row.limitations = f.limitations


def summarize_findings(out: Collector) -> dict[str, Any]:
    counts = {s.value: 0 for s in Severity}
    for f in out.findings.values():
        counts[f.severity.value] += 1
    top = sorted(out.findings.values(), key=lambda f: SEVERITY_ORDER[f.severity])[:5]
    return {
        "finding_count": len(out.findings),
        "evidence_count": len(out.evidence),
        "by_severity": counts,
        "top": [{"finding_id": f.finding_id, "title": f.title, "severity": f.severity.value} for f in top],
    }


def refresh_summary(db: Session, scan: Scan) -> None:
    rows = db.execute(select(Finding).where(Finding.scan_id == scan.id)).scalars().all()
    counts = {s.value: 0 for s in Severity}
    for r in rows:
        counts[r.severity] = counts.get(r.severity, 0) + 1
    ev = db.execute(select(Evidence.id).where(Evidence.scan_id == scan.id)).all()
    top = sorted(rows, key=lambda r: SEVERITY_ORDER.get(Severity(r.severity), 9))[:5]
    scan.summary = {
        "finding_count": len(rows),
        "evidence_count": len(ev),
        "by_severity": counts,
        "top": [{"finding_id": r.finding_id, "title": r.title, "severity": r.severity} for r in top],
    }


def persist_collector(db: Session, scan: Scan, out: Collector, simulation_id: str | None) -> None:
    _persist_collector(db, scan, out, simulation_id)
    db.flush()
    refresh_summary(db, scan)
