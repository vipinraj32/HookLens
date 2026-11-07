"""Position-aware interpretation of scenario steps.

A removal that reverts is only evidence of a *blocked withdrawal* when the LP actually held a
position at that moment. When the earlier add failed (for example a hook that rejects deposits),
the PoolManager reverts the removal with `CannotUpdateEmptyPosition()` because there is nothing
to remove. That says nothing about withdrawals: the withdrawal was simply not tested.

Position existence is taken from execution evidence only, in this order:
  1. the harness metric `position_liquidity_before` recorded on the step (harness >= 1.1.0);
  2. the PoolManager's own empty-position revert in the step's decoded revert data.
A revert string alone is never read as a vulnerability.
"""

from __future__ import annotations

from typing import Any, Literal

from app.services.evm import selector

EMPTY_POSITION_ERROR = "CannotUpdateEmptyPosition"
EMPTY_POSITION_SELECTOR = selector(f"{EMPTY_POSITION_ERROR}()").lower()

# Run statuses that mean no valid test executed.
UNSUPPORTED_RUN = frozenset({"unsupported", "skipped"})
EXECUTION_ERROR_RUN = frozenset({"infra_error", "timed_out", "cancelled"})
PENDING_RUN = frozenset({"queued", "running"})

RemovalOutcome = Literal["completed", "blocked", "not_tested_no_position"]
PositionStatus = Literal["created", "rejected", "not_attempted"]
WithdrawalStatus = Literal["completed", "blocked", "not_tested", "unsupported", "execution_error"]


def _walk_reverts(rev: Any) -> list[dict[str, Any]]:
    """The decoded revert plus any nested inner/details errors (WrappedError chains)."""
    out: list[dict[str, Any]] = []
    stack = [rev]
    while stack:
        r = stack.pop()
        if not isinstance(r, dict):
            continue
        out.append(r)
        stack.extend((r.get("inner"), r.get("details")))
    return out


def is_empty_position_revert(step: dict[str, Any]) -> bool:
    """True when the step reverted because the LP had no position to modify."""
    if step.get("observed") != "revert":
        return False
    raw = str(step.get("revert_data") or "").lower()
    if raw.startswith(EMPTY_POSITION_SELECTOR):
        return True
    for r in _walk_reverts(step.get("revert")):
        if str(r.get("selector") or "").lower() == EMPTY_POSITION_SELECTOR or r.get("name") == EMPTY_POSITION_ERROR:
            return True
    return False


def position_liquidity_before(step: dict[str, Any]) -> int | None:
    """The harness-recorded LP position liquidity immediately before this step, if recorded."""
    v = (step.get("metrics") or {}).get("position_liquidity_before")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def had_no_position(step: dict[str, Any]) -> bool:
    """Execution evidence that the LP held no position when this step ran."""
    liq = position_liquidity_before(step)
    if liq is not None:
        return liq == 0
    return is_empty_position_revert(step)


def is_removal_step(step: dict[str, Any]) -> bool:
    name = str(step.get("name") or "")
    return "remove" in name or name.startswith("recover_after_")


def is_add_step(step: dict[str, Any]) -> bool:
    name = str(step.get("name") or "")
    return name in ("add_liquidity", "re_add_liquidity", "seed_liquidity") or name.startswith("add_before_")


def removal_outcome(step: dict[str, Any]) -> RemovalOutcome | None:
    """Classify a removal step from its evidence; None for steps that are not removals."""
    if not is_removal_step(step):
        return None
    if had_no_position(step):
        return "not_tested_no_position"
    if step.get("observed") == "success":
        return "completed"
    if step.get("observed") == "revert":
        return "blocked"
    return None


def _revert_message(step: dict[str, Any]) -> str | None:
    return (step.get("revert") or {}).get("message")


def position_creation(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Did the scenario's first add create an LP position? Evidence: the add step's outcome."""
    for s in steps:
        if not is_add_step(s):
            continue
        if s.get("observed") == "success":
            return {"status": "created", "step": s["name"], "revert": None}
        if s.get("observed") == "revert":
            return {"status": "rejected", "step": s["name"], "revert": _revert_message(s)}
    return {"status": "not_attempted", "step": None, "revert": None}


def annotate_step(step: dict[str, Any]) -> dict[str, Any]:
    """A copy of the step with `position_check` and `withdrawal_outcome` derived from evidence."""
    s = dict(step)
    liq = position_liquidity_before(s)
    s["position_check"] = {
        "had_position": None if liq is None and not is_empty_position_revert(s) else not had_no_position(s),
        "basis": (
            "harness metric position_liquidity_before"
            if liq is not None
            else ("PoolManager reverted with CannotUpdateEmptyPosition()" if is_empty_position_revert(s) else None)
        ),
    }
    outcome = removal_outcome(s)
    if outcome is not None:
        s["withdrawal_outcome"] = outcome
    if had_no_position(s):
        s["step_status"] = "not_tested"
    return s


def annotate_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [annotate_step(s) for s in steps or []]


def withdrawal_summary(runs: dict[str, Any]) -> dict[str, Any]:
    """Withdrawal evidence across the withdrawal-relevant scenarios of one simulation.

    `runs` maps scenario_id to an object with `status` and `steps` (ORM rows or dicts).
    """
    relevant = ("withdrawal_failure", "oracle_failure", "admin_upgrade")
    outcomes: list[dict[str, Any]] = []
    unsupported: list[str] = []
    errors: list[str] = []
    creation: dict[str, Any] | None = None
    for sid in relevant:
        r = runs.get(sid)
        if r is None:
            continue
        run_status = getattr(r, "status", None) if not isinstance(r, dict) else r.get("status")
        steps = (getattr(r, "steps", None) if not isinstance(r, dict) else r.get("steps")) or []
        if run_status in UNSUPPORTED_RUN:
            unsupported.append(sid)
            continue
        if run_status in EXECUTION_ERROR_RUN or run_status in PENDING_RUN:
            errors.append(sid)
            continue
        if creation is None or creation["status"] == "not_attempted":
            creation = {**position_creation(steps), "scenario": sid}
        for s in steps:
            outcome = removal_outcome(s)
            if outcome is None:
                continue
            outcomes.append(
                {
                    "scenario": sid,
                    "step": s["name"],
                    "condition": s.get("condition"),
                    "outcome": outcome,
                    "revert": _revert_message(s),
                }
            )
    status: WithdrawalStatus
    if any(o["outcome"] == "blocked" for o in outcomes):
        status = "blocked"
    elif any(o["outcome"] == "completed" for o in outcomes):
        status = "completed"
    elif outcomes:
        status = "not_tested"
    elif errors:
        status = "execution_error"
    elif unsupported:
        status = "unsupported"
    else:
        status = "not_tested"
    return {
        "status": status,
        "position_creation": creation or {"status": "not_attempted", "step": None, "revert": None, "scenario": None},
        "outcomes": outcomes,
        "unsupported_scenarios": unsupported,
        "execution_error_scenarios": errors,
    }
