"""End-to-end static scans of real Solidity fixtures with known expected behaviour."""

from __future__ import annotations

from typing import Any

from conftest import by_contract


def contracts(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in report["contracts"]}


def test_scan_completes(report: dict[str, Any]) -> None:
    assert report["scan"]["status"] == "completed"
    assert report["scan"]["problems"] == []
    assert report["compilation"][0]["solc_version"] == "0.8.26"  # from foundry.toml
    assert report["compilation"][0]["evm_version"] == "cancun"
    assert report["execution_results"] is None  # static scans never claim execution results


def test_hook_identification(report: dict[str, Any]) -> None:
    c = contracts(report)
    for name in ("NormalHook", "OracleHook", "DynamicFeeHook", "ReturnDeltaHook", "WithdrawalLockHook",
                 "FalsePositiveHook", "InitializableHook"):  # fmt: skip
        assert c[name]["kind"] == "hook", name
        assert c[name]["confidence"] == "high"
        assert c[name]["analyzed"]
        assert any("IHooks" in r for r in c[name]["reasons"])
    assert c["CandidateHook"]["kind"] == "candidate" and c["CandidateHook"]["confidence"] == "low"
    assert c["HookProxy"]["kind"] == "candidate"
    assert any("DELEGATECALL" in r for r in c["HookProxy"]["reasons"])
    assert c["MiniBaseHook"]["kind"] == "abstract-hook" and not c["MiniBaseHook"]["analyzed"]
    assert c["IPriceFeed"]["kind"] == "interface"


def test_non_hook_is_not_analysed(report: dict[str, Any]) -> None:
    v = contracts(report)["Vault"]
    assert v["kind"] == "not-a-hook" and not v["analyzed"]
    assert not any(f["contract"] == "Vault" for f in report["_all_findings"])


def test_mocks_and_tests_are_excluded(report: dict[str, Any]) -> None:
    excluded = {x["file"] for x in report["files"]["excluded"]}
    assert "src/mocks/MockHook.sol" in excluded
    assert "MockHook" not in contracts(report)
    assert not any(f.startswith("test/") for f in report["files"]["selected"])


def test_permissions_from_declaration(report: dict[str, Any]) -> None:
    c = contracts(report)
    assert c["NormalHook"]["permissions"]["source"] == "declared"
    assert c["NormalHook"]["permissions"]["enabled_flags"] == ["BEFORE_SWAP", "AFTER_SWAP"]
    assert c["ReturnDeltaHook"]["permissions"]["return_delta_flags"] == ["AFTER_SWAP_RETURNS_DELTA"]
    assert c["WithdrawalLockHook"]["permissions"]["can_affect_withdrawals"] is True
    assert c["CandidateHook"]["permissions"]["source"] == "implemented-callbacks"


def test_normal_hook_has_only_informational_findings(report: dict[str, Any]) -> None:
    fs = [f for f in report["_all_findings"] if f["contract"] == "NormalHook"]
    assert fs and all(f["severity"] == "informational" for f in fs)
    assert {f["rule_id"] for f in fs} == {"enabled_callbacks"}


def test_oracle_dependent_hook(report: dict[str, Any]) -> None:
    rules = by_contract(report)["OracleHook"]
    assert {"oracle_dependency", "oracle_replaceable", "callback_external_calls"} <= rules


def test_dynamic_fee_hook(report: dict[str, Any]) -> None:
    f = next(
        f
        for f in report["_all_findings"]
        if f["contract"] == "DynamicFeeHook" and f["rule_id"] == "dynamic_fee_control"
    )
    assert f["severity"] in ("medium", "high")
    assert f["location"]["file"].endswith("DynamicFeeHook.sol")


def test_return_delta_hook(report: dict[str, Any]) -> None:
    rules = by_contract(report)["ReturnDeltaHook"]
    assert {"return_delta_after_swap_returns_delta", "custom_accounting"} <= rules


def test_withdrawal_lock_found_through_virtual_dispatch(report: dict[str, Any]) -> None:
    """The lock lives in `_beforeRemoveLiquidity`, reached from the base hook's external callback."""
    f = next(
        f
        for f in report["_all_findings"]
        if f["contract"] == "WithdrawalLockHook" and f["rule_id"] == "withdrawal_revert_conditions"
    )
    assert f["severity"] == "medium"
    assert "_beforeRemoveLiquidity" in f["description"] and "unlockTime" in f["description"]
    assert f["location"]["file"] == "src/hooks/WithdrawalLockHook.sol"
    assert "privileged_state_in_callback" in by_contract(report)["WithdrawalLockHook"]


def test_pool_manager_caller_check_is_not_a_withdrawal_risk(report: dict[str, Any]) -> None:
    for f in report["_all_findings"]:
        if f["rule_id"] == "withdrawal_revert_conditions":
            assert "NotPoolManager" not in f["description"], f["contract"]


def test_false_positive_hook_stays_quiet(report: dict[str, Any]) -> None:
    fs = [f for f in report["_all_findings"] if f["contract"] == "FalsePositiveHook"]
    assert all(f["severity"] == "informational" for f in fs), [(f["rule_id"], f["severity"]) for f in fs]
    assert "withdrawal_revert_conditions" not in {f["rule_id"] for f in fs}
    assert "privileged_state_in_callback" not in {f["rule_id"] for f in fs}


def test_upgradeable_hook(report: dict[str, Any]) -> None:
    assert {"delegating_proxy_source", "uups_upgrade_function", "permissions_undetermined"} <= by_contract(report)[
        "HookProxy"
    ]
    init = by_contract(report)["InitializableHook"]
    assert {"unguarded_initializer", "pause_mechanism", "withdrawal_revert_conditions"} <= init


def test_findings_are_complete_and_stable(report: dict[str, Any], project: Any) -> None:
    from hooklens.config import ScanConfig
    from hooklens.scanner import SourceInfo, run_scan

    for f in report["_all_findings"]:
        assert f["rule"].startswith("HL.") and f["id"].startswith("HL-")
        assert f["status"] == "inferred"  # static findings are never presented as observed
        assert f["severity_rationale"] and f["description"]
        for loc in f["locations"]:
            assert loc["start_line"] >= 1 and loc["end_line"] >= loc["start_line"]
    again = run_scan(project, ScanConfig(contracts=["OracleHook"]), SourceInfo("local", str(project)))
    a = {f["id"] for f in report["_all_findings"] if f["contract"] == "OracleHook"}
    assert {f["id"] for f in again["_all_findings"]} == a  # same ids across runs


def test_severity_threshold_and_fail_on(project: Any) -> None:
    from hooklens.config import ScanConfig
    from hooklens.scanner import SourceInfo, fails, run_scan

    r = run_scan(project, ScanConfig(severity_threshold="medium"), SourceInfo("local", str(project)))
    assert all(f["severity"] in ("medium", "high", "critical") for f in r["findings"])
    assert r["summary"]["suppressed_below_threshold"] > 0
    assert r["summary"]["findings_total"] == len(r["_all_findings"])
    assert fails(r, "medium") and fails(r, "low")
    assert not fails(r, "high") and not fails(r, "never")


def test_analyzer_selection(project: Any) -> None:
    from hooklens.config import ScanConfig
    from hooklens.scanner import SourceInfo, run_scan

    r = run_scan(
        project, ScanConfig(analyzers=["permissions"], contracts=["OracleHook"]), SourceInfo("local", str(project))
    )
    assert {f["analyzer"] for f in r["_all_findings"]} == {"permissions"}
    assert r["scan"]["configuration"]["analyzers"] == ["permissions"]
