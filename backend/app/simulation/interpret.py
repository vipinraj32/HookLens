"""Turns a forge scenario execution into statuses, annotated steps and observed findings.

Statuses are decided mechanically from what the harness recorded; findings are only derived
from steps whose LP expectation was not met, through a fixed rule table, so the same execution
always yields the same findings and severities.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.analyzers.core import Collector, ConfidenceBasis, FindingStatus, Severity
from app.simulation.catalog import ScenarioDef
from app.simulation.decode import Registry, decode_revert
from app.simulation.forge_runner import ForgeRun
from app.simulation.traces import TraceParseError, first_revert_chain, parse_test_result

CONDITION_TEXT = {
    "oracle_revert": "the oracle call reverts",
    "oracle_zero": "the oracle reports a zero price",
    "oracle_negative": "the oracle reports a negative price",
    "oracle_stale": "the oracle price is older than the hook's staleness window",
    "oracle_jump_10x": "the oracle price jumps 10x",
    "paused": "the owner pauses the hook",
    "external_revert": "an external dependency reverts",
    "upgraded_implementation": "the proxy is upgraded to a reverting implementation",
}
_INFRA_HINTS = re.compile(
    r"(could not instantiate forked environment|failed to get account|"
    r"error sending request|connection refused|missing trie node|header not found|"
    r"block .* not found|historical state .* not available|429|rate limit)",
    re.I,
)


@dataclass
class Interpretation:
    status: str
    reason: str
    forge_status: str | None
    steps: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None


def step_status(step: dict[str, Any]) -> str:
    exp, obs = step.get("lp_expectation"), step.get("observed")
    if exp == "success":
        return "passed" if obs == "success" else "unexpected_revert"
    if exp == "revert":
        return "expected_revert" if obs == "revert" else "failed"
    if not step.get("expectation_met", True):
        return "failed"
    return "observed_revert" if obs == "revert" else "observed"


def _forge_test(output: dict[str, Any] | None, contract: str) -> dict[str, Any] | None:
    if not output:
        return None
    for path, suite in output.items():
        if path.endswith(f":{contract}"):
            results = suite.get("test_results") or {}
            return next(iter(results.values()), None)
    return None


def interpret(sdef: ScenarioDef, run: ForgeRun, out_dir: Path, reg: Registry, labels: dict[str, str]) -> Interpretation:
    if run.status in ("timed_out", "cancelled"):
        return Interpretation(
            run.status,
            f"Scenario {run.status.replace('_', ' ')} after {run.duration_ms} ms",
            None,
            error={"code": run.status, "message": run.stderr_tail[-500:]},
        )
    if run.status == "spawn_error":
        return Interpretation(
            "infra_error",
            "Could not start forge",
            None,
            error={"code": "forge_unavailable", "message": run.stderr_tail},
        )
    test = _forge_test(run.output, sdef.contract)
    forge_status = test.get("status") if test else None
    result_path = out_dir / sdef.result_file
    result = None
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result = None

    if result is None:
        reason_text = (test or {}).get("reason") or run.parse_error or run.stderr_tail[-800:] or "no output"
        code = "fork_unavailable" if _INFRA_HINTS.search(reason_text or "") else "harness_setup_failed"
        if forge_status == "Skipped":
            return Interpretation("skipped", "forge skipped the test (scenario not configured)", forge_status)
        return Interpretation(
            "infra_error",
            "The fork or harness setup failed before the scenario could record results: " + str(reason_text)[:300],
            forge_status,
            error={"code": code, "message": str(reason_text)[:2000]},
        )

    trace: dict[str, Any] = {}
    trace_error = None
    if test is not None:
        try:
            trace = parse_test_result(test, reg, labels)
        except TraceParseError as e:
            trace_error = str(e)
    steps = []
    for raw in result.get("steps", []):
        s = dict(raw)
        s["step_status"] = step_status(s)
        if s.get("revert_data") and s["revert_data"] != "0x":
            s["revert"] = decode_revert(s["revert_data"], reg)
        ids = (trace.get("steps") or {}).get(s["name"], [])
        s["trace_nodes"] = ids
        if s["observed"] == "revert" and ids:
            s["revert_chain"] = first_revert_chain(trace, ids)
        steps.append(s)

    meta = {k: v for k, v in result.items() if k != "steps"}
    meta["forge_duration"] = (run.output or {}).get(next(iter(run.output or {}), ""), {}).get("duration")
    if trace_error:
        meta["trace_error"] = trace_error
    if result.get("infra_error"):
        return Interpretation(
            "infra_error",
            f"Harness reported: {result['infra_error']}",
            forge_status,
            steps,
            trace,
            meta,
            {"code": result["infra_error"], "message": result["infra_error"]},
        )
    if not steps:
        return Interpretation("inconclusive", "The scenario recorded no steps", forge_status, steps, trace, meta)

    violated = [s for s in steps if not s.get("expectation_met", True)]
    not_applied = [s for s in steps if s["name"].startswith("condition_")]
    if violated:
        only_reverts = all(s["step_status"] == "unexpected_revert" for s in violated)
        status = "unexpected_revert" if only_reverts else "failed"
        reason = f"{len(violated)} LP expectation(s) not met: " + ", ".join(s["name"] for s in violated[:6])
    elif not_applied:
        status = "partial"
        reason = "Some conditions could not be applied: " + ", ".join(
            f"{s['name'][10:]} ({s.get('note') or 'not applicable'})" for s in not_applied
        )
    else:
        status = "passed"
        reason = f"All {len(steps)} recorded step(s) met their LP expectation under this configuration"
    return Interpretation(status, reason, forge_status, steps, trace, meta)


# ---------------------------------------------------------------- observed findings


def _rule(scenario: str, step: dict[str, Any]) -> tuple[str, Severity, str, str, str] | None:
    """(rule_id, severity, title, rationale, lp_implication) for a violated step."""
    name, cond, phase = step["name"], step.get("condition", ""), step.get("phase", "")
    cond_text = CONDITION_TEXT.get(cond, cond.replace("_", " "))
    if name.startswith("remove_under_") or name == "remove_after_upgrade":
        privileged = cond in ("paused", "upgraded_implementation")
        sev = Severity.MEDIUM if cond == "paused" else Severity.HIGH
        return (
            f"withdrawal_blocked_{cond}",
            sev,
            f"Liquidity removal reverted when {cond_text}",
            (
                "A privileged action blocked withdrawals in the fork."
                if privileged
                else "A third-party failure, outside the LP's and the hook owner's control, blocked withdrawals in the fork."
            ),
            "While this condition holds, LPs cannot withdraw their liquidity from the pool.",
        )
    if name.startswith("recover_after_") and cond == "paused":
        # The harness deliberately does not unpause: recovery would need the owner.
        return (
            "withdrawal_requires_owner_paused",
            Severity.MEDIUM,
            "Withdrawals stay blocked until the owner unpauses",
            "No unprivileged action restored withdrawals while the hook was paused.",
            "LP exits depend on the owner's willingness to unpause.",
        )
    if name.startswith("recover_after_"):
        return (
            f"withdrawal_not_recovered_{cond}",
            Severity.HIGH,
            f"Liquidity removal still failed after '{cond_text}' was cleared",
            "Withdrawals did not recover once the triggering condition was removed by an unprivileged party.",
            "LPs may need the hook owner to act before they can withdraw.",
        )
    if name == "ordering_remove_after_update":
        return (
            "withdrawal_after_refresh_failed",
            Severity.HIGH,
            "Removal failed even after the oracle was refreshed",
            "Withdrawals did not succeed with a fresh oracle answer.",
            "LP withdrawals may stay blocked.",
        )
    if name.startswith("unauthorized_"):
        return (
            f"unauthorized_call_succeeded_{name[13:]}",
            Severity.CRITICAL,
            f"Unprivileged account succeeded calling {name[13:]}",
            "An account with no role changed hook configuration in the fork.",
            "Anyone can change behaviour that affects LP positions.",
        )
    if scenario == "accounting_invariants" or name.startswith("invariant_"):
        return (
            f"accounting_violation_{name}",
            Severity.HIGH,
            f"Accounting check failed: {name}",
            "Balance changes did not match the PoolManager deltas or tokens were not conserved.",
            "LP or trader balances may change by more than the reported deltas.",
        )
    if phase in ("baseline", "repeat", "liquidity_ordering", "setup", "liquidity"):
        return (
            f"baseline_operation_failed_{name}",
            Severity.HIGH,
            f"Baseline operation failed: {name}",
            "An ordinary LP operation reverted without any adverse condition applied.",
            "Ordinary LP operations may fail with this hook.",
        )
    return (
        f"expectation_not_met_{name}",
        Severity.MEDIUM,
        f"LP expectation not met: {name}",
        "The step's expected LP outcome did not occur.",
        "Review the trace for impact on LPs.",
    )


def observed_findings(
    out: Collector, scenario: str, interp: Interpretation, *, simulation_id: str, repro: str
) -> list[str]:
    ids: list[str] = []
    if interp.status in ("infra_error", "skipped", "unsupported", "timed_out", "cancelled"):
        return ids
    for s in interp.steps:
        if s.get("expectation_met", True):
            continue
        rule = _rule(scenario, s)
        if rule is None:
            continue
        rule_id, sev, title, why, lp = rule
        revert_msg = (s.get("revert") or {}).get("message")
        ev = out.evidence_item(
            "simulation_step",
            f"{simulation_id}:{scenario}:{s['name']}",
            f"{scenario} / {s['name']}",
            ConfidenceBasis.SIMULATION,
            {
                "simulation_id": simulation_id,
                "scenario": scenario,
                "step": s,
                "repro_command": repro,
                "fork_block": interp.meta.get("block_number"),
            },
        )
        desc = (
            f"In scenario `{scenario}` at fork block {interp.meta.get('block_number')}, step `{s['name']}` expected "
            f"`{s.get('lp_expectation')}` but observed `{s.get('observed')}`"
            + (f" with revert: {revert_msg}" if revert_msg else "")
            + "."
        )
        # Withdrawal outcomes are keyed by condition so the same observation from several
        # scenarios (withdrawal_failure and oracle_failure) is one finding with merged evidence.
        location = (
            f"withdrawal:{s.get('condition')}" if rule_id.startswith("withdrawal_") else f"{scenario}:{s['name']}"
        )
        fid = out.finding(
            analyzer_id="simulation",
            code="SIM",
            rule_id=rule_id,
            location=location,
            category="simulation",
            title=title,
            severity=sev,
            severity_rationale=why,
            confidence_basis=ConfidenceBasis.SIMULATION,
            description=desc,
            affected_functions=[c["function"] for c in s.get("revert_chain", []) if c.get("function")][-1:],
            evidence_ids=[ev],
            related_scenarios=[scenario],
            lp_implications=lp,
            remediation="Reproduce with the recorded command, then review the reverting frame in the trace.",
            limitations=[
                "Observed under one fork block, one pool and the recorded parameters only.",
                *(
                    ["The condition was induced with Foundry cheatcodes (mocked calls or impersonation)."]
                    if s.get("condition") not in ("baseline", "")
                    else []
                ),
            ],
            status=FindingStatus.OBSERVED,
        )
        ids.append(fid)
    if scenario == "fee_escalation":
        ids += _fee_change_finding(out, interp, simulation_id=simulation_id, repro=repro)
    return ids


def _fee_pips(step: dict[str, Any]) -> int | None:
    v = (step.get("metrics") or {}).get("lp_fee_pips")
    try:
        return int(v) if v is not None and step.get("observed") == "success" else None
    except (TypeError, ValueError):
        return None


def _fee_change_finding(out: Collector, interp: Interpretation, *, simulation_id: str, repro: str) -> list[str]:
    base = [f for s in interp.steps if s.get("phase") == "baseline" and (f := _fee_pips(s)) is not None]
    after = [(s, f) for s in interp.steps if s.get("phase") == "post_update" and (f := _fee_pips(s)) is not None]
    if not base or not after:
        return []
    baseline = max(base)
    step, peak = max(after, key=lambda x: x[1])
    if peak <= baseline:
        return []
    sev = Severity.HIGH if peak >= 500_000 else Severity.MEDIUM
    ev = out.evidence_item(
        "simulation_step",
        f"{simulation_id}:fee_escalation:{step['name']}",
        f"fee_escalation / {step['name']}",
        ConfidenceBasis.SIMULATION,
        {
            "simulation_id": simulation_id,
            "scenario": "fee_escalation",
            "step": step,
            "baseline_fee_pips": baseline,
            "observed_fee_pips": peak,
            "repro_command": repro,
        },
    )
    return [
        out.finding(
            analyzer_id="simulation",
            code="SIM",
            rule_id="fee_raised_by_owner",
            location="fee_escalation",
            category="fees",
            title=f"Owner raised the effective LP fee from {baseline} to {peak} pips",
            severity=sev,
            severity_rationale=(
                "The fee measured from the PoolManager Swap event rose after an owner-only call; at "
                f"{peak / 10_000:.2f}% swaps become uneconomic or return nothing, removing LP fee income."
            ),
            confidence_basis=ConfidenceBasis.SIMULATION,
            description=(
                f"Baseline swaps paid {baseline} pips ({baseline / 10_000:.4f}%). After `{step['name'][11:]}` the "
                f"swap paid {peak} pips ({peak / 10_000:.4f}%). The change was executed by impersonating the "
                "detected owner in the fork."
            ),
            evidence_ids=[ev],
            related_scenarios=["fee_escalation"],
            lp_implications="LP fee income and pool volume depend on the owner's fee decisions.",
            remediation="Cap the fee at a documented maximum enforced on-chain, and timelock fee-bound changes.",
            limitations=["Measured on one swap size at one fork block."],
            status=FindingStatus.OBSERVED,
        )
    ]


def findings_for_simulation(hook: str, sim: Any) -> Collector:
    """Re-derive the observed findings of one simulation from its stored runs (deterministic)."""
    out = Collector(scope=hook)
    for r in sim.runs:
        interp = Interpretation(
            r.status, r.status_reason, r.forge_status, list(r.steps or []), {}, dict(r.result_meta or {})
        )
        observed_findings(out, r.scenario_id, interp, simulation_id=sim.id, repro=r.repro_command)
    return out
