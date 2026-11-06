"""Simulation orchestration: plan -> forge scenario runs -> interpretation -> observed findings."""

from __future__ import annotations

import contextlib
import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chains import get_chain
from app.config import get_settings
from app.db.base import session_scope
from app.db.models import Contract, Scan, ScenarioRun, Simulation, utcnow
from app.errors import AppError, NotFound, RpcNotConfigured
from app.jobs.dispatch import get_dispatcher
from app.jobs.manager import JobContext, create_job, on_terminal, register
from app.services.scan_service import persist_collector
from app.simulation import forge_runner
from app.simulation.catalog import SCENARIOS
from app.simulation.decode import registry
from app.simulation.interpret import interpret, observed_findings
from app.simulation.planner import build_spec
from hooklens.analyzers.core import Collector

log = logging.getLogger(__name__)
SIM_ROOT_REL = "sim-out/runs"


def _run_dir_rel(sim_id: str) -> str:
    return f"{SIM_ROOT_REL}/{sim_id}"


def create_simulation(db: Session, *, workspace_id: str, scan_id: str, options: dict[str, Any]) -> Simulation:
    scan = db.get(Scan, scan_id)
    if scan is None or scan.workspace_id != workspace_id:
        raise NotFound("scan", scan_id)
    if scan.status not in ("completed", "partial"):
        raise AppError(
            "scan_not_ready", f"The scan is {scan.status}; simulations need a completed scan.", status_code=409
        )
    chain = get_chain(scan.chain_id)
    if not chain.rpc_configured:
        raise RpcNotConfigured(scan.chain_id)
    if forge_runner.forge_path() is None:
        raise AppError(
            "forge_unavailable", "Foundry (forge) is not installed on the simulation worker.", status_code=503
        )
    contract = db.get(Contract, scan.contract_id) if scan.contract_id else None
    sim = Simulation(
        workspace_id=workspace_id,
        scan_id=scan.id,
        chain_id=scan.chain_id,
        status="queued",
        fork_block=scan.block_number,
        fork_block_hash=getattr(contract, "block_hash", None),
    )
    db.add(sim)
    db.flush()
    spec = build_spec(scan, contract, options, run_dir_rel=_run_dir_rel(sim.id))
    sim.spec = spec.to_dict()
    sim.pool_id = spec.data["pool"]["pool_id"]
    sim.harness_version = spec.data["harness"]["version"]
    sim.harness_commit = spec.data["harness"]["digest"]
    for p in spec.scenarios:
        sdef = SCENARIOS[p.scenario_id]
        db.add(
            ScenarioRun(
                simulation_id=sim.id,
                scenario_id=p.scenario_id,
                status="queued" if p.applicable else "unsupported",
                status_reason=p.reason if not p.applicable else "Queued",
                parameters={"env": p.env, **p.parameters, "notes": p.notes},
                repro_command=forge_runner.repro_command(sdef.contract, sim.fork_block, p.env) if p.applicable else "",
            )
        )
    if not any(p.applicable for p in spec.scenarios):
        sim.status = "unsupported"
        sim.summary = _summary([("unsupported", p.scenario_id) for p in spec.scenarios])
        db.commit()
        return sim
    s = get_settings()
    job = create_job(
        db,
        kind="simulation",
        workspace_id=workspace_id,
        subject_id=sim.id,
        payload={"simulation_id": sim.id},
        timeout_s=s.simulation_timeout_s,
        max_attempts=1,
    )
    sim.job_id = job.id
    db.commit()
    get_dispatcher().dispatch(job.id)
    return sim


def _summary(rows: list[tuple[str, str]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for status, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    return {"by_status": counts, "scenarios": {sid: st for st, sid in rows}}


@on_terminal("simulation")
def _sim_terminal(payload: dict[str, Any], status: str, error: dict[str, Any] | None) -> None:
    with session_scope() as db:
        sim = db.get(Simulation, payload.get("simulation_id"))
        if sim is None:
            return
        for r in sim.runs:
            if r.status in ("queued", "running"):
                r.status = (
                    "cancelled" if status == "cancelled" else ("timed_out" if status == "timed_out" else "skipped")
                )
                r.status_reason = f"Simulation {status.replace('_', ' ')} before this scenario finished"
        sim.status = status
        sim.error = error
        sim.finished_at = utcnow()
        sim.summary = _summary([(r.status, r.scenario_id) for r in sim.runs])


@register("simulation")
def run_simulation_job(jc: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    sim_id = payload["simulation_id"]
    s = get_settings()
    with session_scope() as db:
        sim = db.get(Simulation, sim_id)
        if sim is None:
            raise NotFound("simulation", sim_id)
        sim.status = "running"
        scan = db.get(Scan, sim.scan_id)
        assert scan is not None
        contract = db.get(Contract, scan.contract_id) if scan.contract_id else None
        spec = dict(sim.spec)
        chain_id, fork_block, hook, scan_id = sim.chain_id, sim.fork_block, scan.hook_address, scan.id
        abi = list(contract.abi or []) if contract and contract.abi else None
        runs = [
            (r.id, r.scenario_id, dict(r.parameters or {}), r.repro_command) for r in sim.runs if r.status == "queued"
        ]
    chain = get_chain(chain_id)
    if not chain.rpc_url:
        raise RpcNotConfigured(chain_id)

    jc.update("building", 0.03, "Compiling the HookLens Foundry harness")
    ok, msg = forge_runner.ensure_built(spec["harness"]["digest"])
    if not ok:
        raise AppError("harness_build_failed", f"forge build failed: {msg}", status_code=500)

    reg = registry(abi)
    labels = _labels(spec)
    run_dir = s.contracts_dir / _run_dir_rel(sim_id)
    statuses: list[tuple[str, str]] = []
    n = len(runs)
    for i, (run_id, sid, params, repro) in enumerate(runs):
        jc.check()
        sdef = SCENARIOS[sid]
        jc.update(
            "simulating", 0.05 + 0.9 * i / max(n, 1), f"Running {sdef.title} ({i + 1}/{n})", data={"scenario": sid}
        )
        with session_scope() as db:
            r = db.get(ScenarioRun, run_id)
            if r is not None:
                r.status, r.status_reason = "running", "Running"
        timeout = int(max(10, min(s.scenario_timeout_s, jc.time_left() - 5)))
        run = forge_runner.run_scenario(
            sdef.contract,
            fork_url=chain.rpc_url,
            fork_block=fork_block,
            scenario_env=params.get("env", {}),
            log_path=run_dir / "logs" / sid,
            timeout_s=timeout,
            should_cancel=jc.cancel_requested,
            heartbeat=jc.heartbeat,
        )
        interp = interpret(sdef, run, run_dir / sid, reg, labels)
        out = Collector(scope=hook)
        finding_ids = observed_findings(out, sid, interp, simulation_id=sim_id, repro=repro)
        with session_scope() as db:
            r = db.get(ScenarioRun, run_id)
            assert r is not None
            r.status, r.status_reason = interp.status, interp.reason
            r.forge_status = interp.forge_status
            r.duration_ms = run.duration_ms
            r.steps = interp.steps
            r.trace = interp.trace
            r.result_meta = {**interp.meta, "finding_ids": finding_ids, "argv": run.argv, "exit_code": run.exit_code}
            r.error = interp.error
            if out.findings or out.evidence:
                scan = db.get(Scan, scan_id)
                assert scan is not None
                persist_collector(db, scan, out, simulation_id=sim_id)
        _cleanup_logs(run_dir / "logs", sid)
        statuses.append((interp.status, sid))
        jc.update(
            "simulating",
            0.05 + 0.9 * (i + 1) / max(n, 1),
            f"{sdef.title}: {interp.status} — {interp.reason[:140]}",
            level="warning" if interp.status in ("failed", "unexpected_revert", "infra_error") else "info",
            data={"scenario": sid, "status": interp.status, "findings": finding_ids},
        )
        if interp.status == "cancelled":
            jc.check()

    with session_scope() as db:
        sim = db.get(Simulation, sim_id)
        assert sim is not None
        all_rows = [(r.status, r.scenario_id) for r in sim.runs]
        executed = [st for st, _ in statuses]
        if executed and all(st == "infra_error" for st in executed):
            sim.status = "failed"
            sim.error = {"code": "infra_error", "message": "Every scenario failed for infrastructure reasons."}
        elif any(st in ("infra_error", "timed_out") for st in executed):
            sim.status = "partial"
        else:
            sim.status = "completed"
        sim.summary = _summary(all_rows)
        sim.finished_at = utcnow()
        final = sim.status
    return {"message": f"Simulation {final}", "simulation_id": sim_id, "status": final}


def _labels(spec: dict[str, Any]) -> dict[str, str]:
    pool = spec.get("pool") or {}
    labels = {spec["hook"]: "Hook"}
    for k, name in (("currency0", "Currency0"), ("currency1", "Currency1")):
        if pool.get(k):
            labels[pool[k]] = (pool.get("token0" if k == "currency0" else "token1") or {}).get("symbol") or name
    owner = (spec.get("privileged_actor") or {}).get("owner")
    if owner:
        labels[owner] = "HookOwner"
    for sc in spec.get("scenarios", []):
        o = (sc.get("parameters") or {}).get("oracle") or {}
        if o.get("address"):
            labels[o["address"]] = "Oracle"
    if spec.get("implementation"):
        labels[spec["implementation"]] = "Implementation"
    return labels


def _cleanup_logs(log_dir: Path, sid: str) -> None:
    # The raw forge JSON is parsed and stored; keep stderr for debugging, drop the large stdout.
    p = log_dir / f"{sid}.stdout.json"
    with contextlib.suppress(OSError):
        p.unlink(missing_ok=True)


def delete_run_dir(sim_id: str) -> None:
    shutil.rmtree(get_settings().contracts_dir / _run_dir_rel(sim_id), ignore_errors=True)


def get_simulation(db: Session, workspace_id: str, sim_id: str) -> Simulation:
    sim = db.get(Simulation, sim_id)
    if sim is None or sim.workspace_id != workspace_id:
        raise NotFound("simulation", sim_id)
    return sim


def list_simulations(db: Session, workspace_id: str, scan_id: str) -> list[Simulation]:
    return list(
        db.execute(
            select(Simulation)
            .where(Simulation.workspace_id == workspace_id, Simulation.scan_id == scan_id)
            .order_by(Simulation.created_at.desc())
        )
        .scalars()
        .all()
    )
