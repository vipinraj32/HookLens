"""Revert decoding, step/scenario status mapping, observed-finding rules and the planner."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from eth_abi import encode

from app.analyzers.core import Collector
from app.errors import AppError
from app.lp import math as m
from app.services.evm import selector
from app.simulation.catalog import SCENARIOS
from app.simulation.decode import Registry, decode_revert
from app.simulation.forge_runner import ForgeRun, repro_command
from app.simulation.interpret import interpret, observed_findings, step_status
from app.simulation.planner import build_spec, plan_position, select_pool

HOOK = "0x9d536C7335f6ca4D20384AaF7F655eb364B00200"


def _reg() -> Registry:
    r = Registry()
    r.add_abi(
        [
            {"type": "error", "name": "InvalidOraclePrice", "inputs": [{"name": "answer", "type": "int256"}]},
            {
                "type": "function",
                "name": "beforeRemoveLiquidity",
                "inputs": [
                    {"name": "sender", "type": "address"},
                    {
                        "name": "key",
                        "type": "tuple",
                        "components": [{"name": "c0", "type": "address"}, {"name": "c1", "type": "address"}],
                    },
                ],
            },
        ]
    )
    return r


def test_decode_error_string_and_panic() -> None:
    reg = _reg()
    d = decode_revert(selector("Error(string)") + encode(["string"], ["nope"]).hex(), reg)
    assert d["kind"] == "error_string" and d["message"] == "nope"
    d = decode_revert(selector("Panic(uint256)") + encode(["uint256"], [0x11]).hex(), reg)
    assert d["kind"] == "panic" and "overflow" in d["message"]


def test_decode_custom_error_and_wrapped() -> None:
    reg = _reg()
    inner = bytes.fromhex(selector("InvalidOraclePrice(int256)")[2:]) + encode(["int256"], [-1])
    fsel = bytes.fromhex(selector("beforeRemoveLiquidity(address,(address,address))")[2:])
    wrapped = "0x90bfb865" + encode(["address", "bytes4", "bytes", "bytes"], [HOOK, fsel, inner, b""]).hex()
    d = decode_revert(wrapped, reg)
    assert d["kind"] == "wrapped"
    assert d["function"] == "beforeRemoveLiquidity(address,(address,address))"
    assert d["inner"]["name"] == "InvalidOraclePrice" and d["inner"]["args"] == {"answer": -1}
    assert "InvalidOraclePrice(answer=-1)" in d["message"]


def test_decode_raw_and_unknown() -> None:
    reg = _reg()
    assert decode_revert("0x" + b"HookLens: mocked".hex(), reg)["message"] == "HookLens: mocked"
    assert decode_revert("0xdeadbeef", reg)["kind"] == "unknown"
    assert decode_revert("0x", reg)["kind"] == "empty"


@pytest.mark.parametrize(
    ("exp", "obs", "status"),
    [
        ("success", "success", "passed"),
        ("success", "revert", "unexpected_revert"),
        ("revert", "revert", "expected_revert"),
        ("revert", "success", "failed"),
        ("observe", "revert", "observed_revert"),
        ("observe", "success", "observed"),
    ],
)
def test_step_status(exp: str, obs: str, status: str) -> None:
    assert (
        step_status(
            {
                "lp_expectation": exp,
                "observed": obs,
                "expectation_met": exp in ("observe", "") or (exp == "success") == (obs == "success"),
            }
        )
        == status
    )


def _write_result(tmp: Path, steps: list[dict], infra: str = "") -> None:
    import json

    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "withdrawal_failure.json").write_text(
        json.dumps(
            {"scenario": "withdrawal_failure", "block_number": 4, "infra_error": infra, "violations": 0, "steps": steps}
        )
    )


def _step(name: str, exp: str, obs: str, cond: str = "baseline", phase: str = "baseline", met: bool = True) -> dict:
    return {
        "name": name,
        "phase": phase,
        "condition": cond,
        "lp_expectation": exp,
        "observed": obs,
        "expectation_met": met,
        "privileged": False,
        "revert_data": "0x",
    }


def _run() -> ForgeRun:
    return ForgeRun("completed", 0, 100, {}, "")


def test_interpret_statuses(tmp_path: Path) -> None:
    sdef = SCENARIOS["withdrawal_failure"]
    reg = Registry()
    _write_result(tmp_path / "a", [_step("add_liquidity", "success", "success")])
    assert interpret(sdef, _run(), tmp_path / "a", reg, {}).status == "passed"

    _write_result(
        tmp_path / "b",
        [
            _step("add_liquidity", "success", "success"),
            _step("remove_under_oracle_zero", "success", "revert", "oracle_zero", "adversarial", met=False),
        ],
    )
    i = interpret(sdef, _run(), tmp_path / "b", reg, {})
    assert i.status == "unexpected_revert" and "remove_under_oracle_zero" in i.reason

    _write_result(tmp_path / "c", [_step("condition_paused", "observe", "revert", "paused", "condition_setup")])
    assert interpret(sdef, _run(), tmp_path / "c", reg, {}).status == "partial"

    _write_result(tmp_path / "d", [], infra="pool_not_initialized")
    assert interpret(sdef, _run(), tmp_path / "d", reg, {}).status == "infra_error"

    assert interpret(sdef, _run(), tmp_path / "missing", reg, {}).status == "infra_error"
    assert interpret(sdef, ForgeRun("timed_out", None, 5, None, ""), tmp_path, reg, {}).status == "timed_out"
    assert interpret(sdef, ForgeRun("cancelled", None, 5, None, ""), tmp_path, reg, {}).status == "cancelled"


def test_observed_findings_are_deterministic_and_merge_by_condition(tmp_path: Path) -> None:
    sdef = SCENARIOS["withdrawal_failure"]
    _write_result(
        tmp_path,
        [
            _step("remove_under_oracle_revert", "success", "revert", "oracle_revert", "adversarial", met=False),
            _step("recover_after_paused", "success", "revert", "paused", "recovery", met=False),
        ],
    )
    i = interpret(sdef, _run(), tmp_path, Registry(), {})
    a, b = Collector(scope=HOOK), Collector(scope=HOOK)
    ids_a = observed_findings(a, "withdrawal_failure", i, simulation_id="s1", repro="x")
    ids_b = observed_findings(b, "oracle_failure", i, simulation_id="s2", repro="x")
    assert ids_a == ids_b  # same hook + condition -> same stable IDs across scenarios and runs
    sev = {f.rule_id: f.severity.value for f in a.findings.values()}
    assert sev == {"withdrawal_blocked_oracle_revert": "high", "withdrawal_requires_owner_paused": "medium"}
    assert all(f.status.value == "observed" and f.confidence_basis.value == "simulation" for f in a.findings.values())


def test_repro_command_never_contains_rpc_url() -> None:
    cmd = repro_command("WithdrawalFailureScenario", 4, {"HL_HOOK": HOOK, "ETH_RPC_URL": "https://secret/key"})
    assert "secret" not in cmd and "HL_HOOK=" in cmd and "--fork-block-number 4" in cmd


def _pool(tick: int = 200340) -> dict:
    return {
        "pool_id": "0x" + "11" * 32,
        "currency0": "0x" + "0a" * 20,
        "currency1": "0x" + "0b" * 20,
        "fee": 3000,
        "dynamic_fee": False,
        "tick_spacing": 60,
        "token0": {"decimals": 6, "symbol": "USD"},
        "token1": {"decimals": 18, "symbol": "WETH"},
        "state": {
            "initialized": True,
            "sqrt_price_x96": str(m.get_sqrt_price_at_tick(tick)),
            "tick": tick,
            "liquidity": "1000",
        },
    }


def test_plan_position_sizes_from_lp_math() -> None:
    p = plan_position(_pool(), {})
    assert p["tick_lower"] == 194340 and p["tick_upper"] == 206400 and p["range_state"] == "in-range"
    assert int(p["liquidity"]) > 0 and int(p["swap_amount0"]) > 0
    assert int(p["mint_amount0"]) <= 10 * 10**6


def test_select_pool_errors() -> None:
    with pytest.raises(AppError):
        select_pool([], None)
    with pytest.raises(AppError):
        select_pool([_pool()], "0x" + "22" * 32)


def test_build_spec_applicability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.simulation.planner._pool_manager", lambda scan: "0x" + "cc" * 20)
    facts = {
        "owner": "0x" + "dd" * 20,
        "oracle": {
            "address": "0x" + "ee" * 20,
            "selector": "0xfeaf968c",
            "kind": "chainlink",
            "callbacks": ["beforeRemoveLiquidity"],
            "staleness": {"variable": "maxStaleness", "seconds": 3600},
        },
        "admin_calls": [{"signature": "setMaxStaleness(uint256)", "types": ["uint256"], "label": "setMaxStaleness"}],
    }
    scan = SimpleNamespace(
        analysis={"facts": facts},
        permissions={"enabled_flags": ["BEFORE_REMOVE_LIQUIDITY"]},
        pools=[_pool()],
        hook_address=HOOK,
        chain_id=31337,
        block_number=4,
    )
    spec = build_spec(scan, None, {}, run_dir_rel="sim-out/runs/x")
    plans = {p.scenario_id: p for p in spec.scenarios}
    assert not plans["fee_escalation"].applicable
    w = plans["withdrawal_failure"]
    assert w.env["HL_CONDITIONS"] == "oracle_revert,oracle_zero,oracle_negative,oracle_stale"
    assert w.env["HL_STALE_SECONDS"] == "3601"  # one second past the hook's own threshold
    assert plans["admin_upgrade"].env["HL_ADMIN_CALLS"].startswith(selector("setMaxStaleness(uint256)"))
    assert plans["oracle_failure"].env["HL_OUT"] == "sim-out/runs/x/oracle_failure"
    assert all(not k.startswith("ETH") for p in spec.scenarios for k in p.env)
