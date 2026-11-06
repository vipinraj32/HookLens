"""AI validator and LangGraph flow with a deterministic fake provider (no network)."""

from __future__ import annotations

from typing import Any

from app.ai.graph import run_explanation
from app.ai.schemas import LpExplanation, SimulationRef, SourceRef, TechnicalExplanation, strict_schema
from app.ai.validator import validate

CTX: dict[str, Any] = {
    "finding": {"finding_id": "HL-ORC-1", "severity": "medium", "title": "Oracle dependency"},
    "evidence": {
        "EV-a": {"evidence_id": "EV-a", "source_file": "src/Hook.sol", "line_start": 60, "line_end": 70},
        "EV-b": {"evidence_id": "EV-b", "source_file": None, "line_start": None, "line_end": None},
    },
    "simulation_steps": [{"scenario": "withdrawal_failure", "step": "remove_under_oracle_stale"}],
}
CTX["facts_text"] = "maxStaleness 3600 block 4 HL-ORC-1"


def _tech(**kw: Any) -> TechnicalExplanation:
    base = dict(
        summary="beforeRemoveLiquidity reads the oracle (EV-a).",
        mechanism="If the answer is older than 3600 seconds the hook reverts (EV-a).",
        evidence_refs=["EV-a"],
        source_refs=[SourceRef(file="src/Hook.sol", line_start=62, line_end=66)],
        simulation_refs=[SimulationRef(scenario="withdrawal_failure", step="remove_under_oracle_stale")],
    )
    base.update(kw)
    return TechnicalExplanation(**base)


def _lp(**kw: Any) -> LpExplanation:
    base = dict(
        what_it_means="Withdrawals depend on oracle freshness.",
        when_it_matters="When the feed stops.",
        what_to_check=["Who can change the oracle"],
        evidence_refs=["EV-b"],
    )
    base.update(kw)
    return LpExplanation(**base)


def test_valid_explanation_passes() -> None:
    assert validate(_tech(), _lp(), CTX).ok


def test_validator_rejections() -> None:
    cases = [
        (_tech(evidence_refs=["EV-zzz"]), _lp(), "not provided"),
        (_tech(source_refs=[SourceRef(file="src/Hook.sol", line_start=50, line_end=80)]), _lp(), "outside"),
        (_tech(simulation_refs=[SimulationRef(scenario="fee_escalation", step="x")]), _lp(), "did not run"),
        (_tech(mechanism="Fees reach 4200 pips (EV-a)."), _lp(), "numbers"),
        (_tech(), _lp(what_it_means="This is a high-severity issue."), "severity"),
        (_tech(), _lp(what_it_means="An attacker can drain the pool."), "unsupported claim"),
        (_tech(), _lp(what_to_check=["The hook is safe"]), "unsupported claim"),
    ]
    for tech, lp, needle in cases:
        r = validate(tech, lp, CTX)
        assert not r.ok and any(needle in e for e in r.errors), (needle, r.errors)


def test_strict_schema_closes_objects() -> None:
    s = strict_schema(TechnicalExplanation)
    assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
    assert all(d["additionalProperties"] is False for d in s["$defs"].values())


class FakeProvider:
    model = "fake"

    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = outputs
        self.calls: list[str] = []

    def generate(self, system: str, user: str, schema: type) -> Any:
        self.calls.append(user)
        return self.outputs.pop(0)


def test_graph_accepts_valid_output() -> None:
    p = FakeProvider([_tech(), _lp()])
    state = run_explanation(p, CTX)
    assert state["status"] == "ready" and state["attempts"] == 1


def test_graph_retries_with_feedback_then_accepts() -> None:
    p = FakeProvider([_tech(evidence_refs=["EV-bad"]), _lp(), _tech(), _lp()])
    state = run_explanation(p, CTX)
    assert state["status"] == "ready" and state["attempts"] == 2
    assert "rejected by the validator" in p.calls[2]


def test_graph_rejects_after_max_attempts() -> None:
    bad = _tech(mechanism="It is exploitable (EV-a).")
    p = FakeProvider([bad, _lp(), bad, _lp()])
    state = run_explanation(p, CTX)
    assert state["status"] == "rejected" and not state["validation"]["ok"]
