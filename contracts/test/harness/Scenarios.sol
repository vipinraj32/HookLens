// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Currency} from "@uniswap/v4-core/src/types/Currency.sol";
import {IERC6909Claims} from "@uniswap/v4-core/src/interfaces/external/IERC6909Claims.sol";
import {OpResult, LPActor, TraderActor, RevertingImplementation} from "../../src/harness/Actors.sol";
import {HookLensScenarioBase} from "./HookLensScenarioBase.sol";

/// @title Scenarios
/// @notice Implementations of the HookLens scenario catalogue. Each `_run*` function executes
///         real transactions against the configured pool and records evidence. Expectations are
///         expressed from the liquidity provider's point of view and never imply a verdict of
///         "safe": a met expectation only means it held under this exact configuration.
abstract contract Scenarios is HookLensScenarioBase {
    // ---------------------------------------------------------------- config structs
    struct OracleConfig {
        address oracle;
        bytes4 selector;
        uint8 kind; // 0 = none, 1 = chainlink latestRoundData shape, 2 = single uint256 price
        uint256 staleSeconds;
    }

    struct WithdrawalConfig {
        string[] conditions; // oracle_revert, oracle_zero, oracle_negative, oracle_stale, paused, external_revert
        OracleConfig oracle;
        bytes pauseCall;
        address[] externalTargets;
    }

    struct FeeConfig {
        bytes[] setterCalls;
        string[] setterLabels;
    }

    struct AdminConfig {
        bytes[] calls;
        string[] labels;
        bytes4 upgradeSelector;
        address proxyAdmin;
    }

    // ---------------------------------------------------------------- env loaders
    function _envOracle() internal view returns (OracleConfig memory o) {
        o.oracle = vm.envOr("HL_ORACLE", address(0));
        o.selector = bytes4(uint32(vm.envOr("HL_ORACLE_SELECTOR", uint256(0xfeaf968c))));
        string memory kind = vm.envOr("HL_ORACLE_KIND", string("chainlink"));
        o.kind = o.oracle == address(0) ? 0 : (keccak256(bytes(kind)) == keccak256("uint") ? 2 : 1);
        o.staleSeconds = vm.envOr("HL_STALE_SECONDS", uint256(7 days));
    }

    function _envWithdrawal() internal view returns (WithdrawalConfig memory w) {
        w.conditions = _envStringList("HL_CONDITIONS");
        w.oracle = _envOracle();
        w.pauseCall = vm.envOr("HL_PAUSE_CALL", bytes(""));
        string memory targets = vm.envOr("HL_EXTERNAL_TARGETS", string(""));
        if (bytes(targets).length > 0) w.externalTargets = vm.envAddress("HL_EXTERNAL_TARGETS", ",");
    }

    function _envFee() internal view returns (FeeConfig memory f) {
        f.setterCalls = _envBytesList("HL_FEE_CALLS");
        f.setterLabels = _envStringList("HL_FEE_LABELS");
    }

    function _envAdmin() internal view returns (AdminConfig memory a) {
        a.calls = _envBytesList("HL_ADMIN_CALLS");
        a.labels = _envStringList("HL_ADMIN_LABELS");
        a.upgradeSelector = bytes4(uint32(vm.envOr("HL_UPGRADE_SELECTOR", uint256(0))));
        a.proxyAdmin = vm.envOr("HL_PROXY_ADMIN", address(0));
    }

    function _label(string[] memory labels, uint256 i, string memory fallbackLabel)
        internal
        pure
        returns (string memory)
    {
        return i < labels.length ? labels[i] : fallbackLabel;
    }

    // ================================================================ S1 fee escalation

    function _runFeeEscalation(FeeConfig memory cfg) internal {
        _begin("fee_escalation");
        if (_abortIfInfraError()) return;

        OpResult memory r = _add(lp, liquidity);
        _record(
            Step("seed_liquidity", "setup", "baseline", "success", false, "LP adds liquidity in the default range"), r
        );

        (OpResult memory s1, uint256 fee1) = _swapWithFee(trader, true, -int256(swapAmount));
        _recordWithMetrics(
            Step(
                "baseline_swap_0_for_1",
                "baseline",
                "baseline",
                "success",
                false,
                "Exact-input swap; fee from Swap event"
            ),
            s1,
            _metricU("lp_fee_pips", fee1)
        );
        (OpResult memory s2, uint256 fee2) = _swapWithFee(trader, false, -int256(swapAmount1));
        _recordWithMetrics(
            Step(
                "baseline_swap_1_for_0",
                "baseline",
                "baseline",
                "success",
                false,
                "Exact-input swap; fee from Swap event"
            ),
            s2,
            _metricU("lp_fee_pips", fee2)
        );

        // Unauthorized attempts: an actor without any role must not be able to change fees.
        for (uint256 i; i < cfg.setterCalls.length; i++) {
            (bool ok, bytes memory ret) = outsider.tryCall(address(key.hooks), cfg.setterCalls[i]);
            _recordRaw(
                Step(
                    string.concat("unauthorized_", _label(cfg.setterLabels, i, "fee_call")),
                    "unauthorized",
                    "unprivileged_caller",
                    "revert",
                    false,
                    "Fee setter called by an account with no role"
                ),
                ok,
                ret,
                0,
                0,
                0,
                ""
            );
        }

        // Authorized sequence: executed by the detected owner via an explicit, recorded prank.
        if (hookOwner != address(0)) {
            for (uint256 i; i < cfg.setterCalls.length; i++) {
                (bool ok, bytes memory ret) = _privilegedCall(hookOwner, address(key.hooks), cfg.setterCalls[i]);
                _recordRaw(
                    Step(
                        string.concat("authorized_", _label(cfg.setterLabels, i, "fee_call")),
                        "authorized",
                        "privileged_owner",
                        "observe",
                        true,
                        "Owner-initiated configuration change (impersonated in the fork only)"
                    ),
                    ok,
                    ret,
                    0,
                    0,
                    0,
                    ""
                );
                if (ok) {
                    (OpResult memory sw, uint256 f) = _swapWithFee(trader, true, -int256(swapAmount));
                    _recordWithMetrics(
                        Step(
                            string.concat("swap_after_", _label(cfg.setterLabels, i, "fee_call")),
                            "post_update",
                            "privileged_owner",
                            "observe",
                            false,
                            "Exact-input swap after configuration change"
                        ),
                        sw,
                        _metricU("lp_fee_pips", f)
                    );
                }
            }
        }
        _finish();
    }

    // ================================================================ S2 withdrawal failure

    function _runWithdrawal(WithdrawalConfig memory cfg) internal {
        _begin("withdrawal_failure");
        if (_abortIfInfraError()) return;

        OpResult memory r = _add(lp, liquidity);
        _record(Step("add_liquidity", "baseline", "baseline", "success", false, "LP adds liquidity"), r);
        r = _swapExactIn(trader, true, swapAmount);
        _record(Step("trader_swap_0_for_1", "baseline", "baseline", "observe", false, "Swap to accrue fees"), r);
        r = _swapExactIn(trader, false, swapAmount1);
        _record(Step("trader_swap_1_for_0", "baseline", "baseline", "observe", false, "Swap to accrue fees"), r);

        uint128 posLiq = _positionLiquidity(lp);
        r = _remove(lp, posLiq / 2);
        _record(
            Step("partial_remove_50pct", "baseline", "baseline", "success", false, "Remove half of the position"), r
        );
        posLiq = _positionLiquidity(lp);
        r = _remove(lp, posLiq);
        _record(Step("full_remove", "baseline", "baseline", "success", false, "Remove the remaining position"), r);

        r = _add(lp, liquidity);
        _record(Step("re_add_liquidity", "repeat", "baseline", "success", false, "Repeated add"), r);
        r = _remove(lp, _positionLiquidity(lp));
        _record(Step("repeat_full_remove", "repeat", "baseline", "success", false, "Repeated full removal"), r);

        for (uint256 i; i < cfg.conditions.length; i++) {
            _withdrawUnderCondition(cfg, cfg.conditions[i]);
        }
        _finish();
    }

    function _withdrawUnderCondition(WithdrawalConfig memory cfg, string memory condition) internal {
        uint256 snap = vm.snapshotState();
        OpResult memory r = _add(lp, liquidity);
        _record(
            Step(
                string.concat("add_before_", condition),
                "condition_setup",
                condition,
                "success",
                false,
                "Fresh position"
            ),
            r
        );

        (bool applied, bool privileged, string memory why) = _applyCondition(cfg, condition);
        if (!applied) {
            _recordRaw(
                Step(string.concat("condition_", condition), "condition_setup", condition, "observe", privileged, why),
                false,
                "",
                0,
                0,
                0,
                ""
            );
            vm.revertToState(snap);
            return;
        }

        uint128 posLiq = _positionLiquidity(lp);
        r = _remove(lp, posLiq);
        _record(
            Step(string.concat("remove_under_", condition), "adversarial", condition, "success", privileged, why), r
        );

        if (!r.ok) {
            // Recovery check: does the position become withdrawable once the condition clears?
            vm.clearMockedCalls();
            _clearCondition(cfg, condition);
            posLiq = _positionLiquidity(lp);
            OpResult memory rec = _remove(lp, posLiq);
            _record(
                Step(
                    string.concat("recover_after_", condition),
                    "recovery",
                    condition,
                    "success",
                    privileged,
                    "Condition removed, removal retried"
                ),
                rec
            );
        }
        vm.clearMockedCalls();
        vm.revertToState(snap);
    }

    function _applyCondition(WithdrawalConfig memory cfg, string memory condition)
        internal
        returns (bool applied, bool privileged, string memory why)
    {
        bytes32 c = keccak256(bytes(condition));
        OracleConfig memory o = cfg.oracle;
        if (c == keccak256("oracle_revert") || c == keccak256("oracle_zero") || c == keccak256("oracle_negative")) {
            if (o.kind == 0) return (false, false, "no oracle dependency configured");
            if (c == keccak256("oracle_revert")) {
                vm.mockCallRevert(o.oracle, abi.encodePacked(o.selector), bytes("HookLens: mocked oracle revert"));
                return (true, false, "Oracle call reverts (mocked)");
            }
            int256 answer = c == keccak256("oracle_zero") ? int256(0) : int256(-1);
            if (o.kind == 2 && answer < 0) return (false, false, "uint oracle cannot report negative values");
            vm.mockCall(o.oracle, abi.encodePacked(o.selector), _oracleReturn(o.kind, answer, vm.getBlockTimestamp()));
            return (
                true,
                false,
                c == keccak256("oracle_zero") ? "Oracle reports zero (mocked)" : "Oracle reports negative (mocked)"
            );
        }
        if (c == keccak256("oracle_stale")) {
            if (o.kind == 0) return (false, false, "no oracle dependency configured");
            vm.warp(vm.getBlockTimestamp() + o.staleSeconds);
            return (true, false, "Time advanced beyond staleness window without oracle update");
        }
        if (c == keccak256("paused")) {
            if (cfg.pauseCall.length == 0 || hookOwner == address(0)) {
                return (false, true, "no pause function or owner detected");
            }
            (bool ok,) = _privilegedCall(hookOwner, address(key.hooks), cfg.pauseCall);
            if (!ok) return (false, true, "owner pause call reverted");
            return (true, true, "Hook paused by its owner (impersonated in the fork only)");
        }
        if (c == keccak256("external_revert")) {
            if (cfg.externalTargets.length == 0) return (false, false, "no external call targets detected");
            for (uint256 i; i < cfg.externalTargets.length; i++) {
                vm.mockCallRevert(cfg.externalTargets[i], bytes(""), bytes("HookLens: mocked external revert"));
            }
            return (true, false, "All calls to detected external targets revert (mocked)");
        }
        return (false, false, "unknown condition");
    }

    function _clearCondition(WithdrawalConfig memory cfg, string memory condition) internal {
        bytes32 c = keccak256(bytes(condition));
        if (c == keccak256("oracle_stale") && cfg.oracle.kind != 0) {
            // Recovery means a fresh oracle answer is published at the current time.
            (bool ok, bytes memory ret) = cfg.oracle.oracle.staticcall(abi.encodePacked(cfg.oracle.selector));
            if (ok && cfg.oracle.kind == 1 && ret.length >= 160) {
                (, int256 answer,,,) = abi.decode(ret, (uint80, int256, uint256, uint256, uint80));
                vm.mockCall(
                    cfg.oracle.oracle,
                    abi.encodePacked(cfg.oracle.selector),
                    _oracleReturn(1, answer, vm.getBlockTimestamp())
                );
            }
        }
        // Pause recovery requires a privileged unpause and is intentionally not attempted:
        // the result shows whether the LP depends on the owner to recover funds.
    }

    function _oracleReturn(uint8 kind, int256 answer, uint256 ts) internal pure returns (bytes memory) {
        if (kind == 2) return abi.encode(uint256(answer));
        return abi.encode(uint80(1), answer, ts, ts, uint80(1));
    }

    // ================================================================ S3 oracle failure

    function _runOracleFailure(OracleConfig memory o) internal {
        _begin("oracle_failure");
        if (_abortIfInfraError()) return;
        if (o.kind == 0) {
            _recordRaw(
                Step(
                    "no_oracle_dependency",
                    "setup",
                    "none",
                    "observe",
                    false,
                    "No oracle dependency was detected or configured"
                ),
                false,
                "",
                0,
                0,
                0,
                ""
            );
            _finish();
            return;
        }
        OpResult memory r = _add(lp, liquidity);
        _record(Step("add_liquidity", "baseline", "baseline", "success", false, "LP adds liquidity"), r);

        string[5] memory conds = ["oracle_revert", "oracle_zero", "oracle_negative", "oracle_stale", "oracle_jump_10x"];
        for (uint256 i; i < conds.length; i++) {
            uint256 snap = vm.snapshotState();
            bool applied = _applyOracleCondition(o, conds[i]);
            if (!applied) {
                _recordRaw(
                    Step(
                        string.concat("condition_", conds[i]),
                        "setup",
                        conds[i],
                        "observe",
                        false,
                        "Not applicable to this oracle shape"
                    ),
                    false,
                    "",
                    0,
                    0,
                    0,
                    ""
                );
                vm.revertToState(snap);
                continue;
            }
            r = _swapExactIn(trader, true, swapAmount);
            _record(
                Step(
                    string.concat("swap_under_", conds[i]),
                    "adversarial",
                    conds[i],
                    "observe",
                    false,
                    "Swap while oracle condition holds"
                ),
                r
            );
            r = _add(lp2, liquidity);
            _record(
                Step(
                    string.concat("add_under_", conds[i]),
                    "adversarial",
                    conds[i],
                    "observe",
                    false,
                    "Add while oracle condition holds"
                ),
                r
            );
            r = _remove(lp, _positionLiquidity(lp));
            _record(
                Step(
                    string.concat("remove_under_", conds[i]),
                    "adversarial",
                    conds[i],
                    "success",
                    false,
                    "LP removal while oracle condition holds"
                ),
                r
            );
            vm.clearMockedCalls();
            vm.revertToState(snap);
        }

        // Update ordering: removal attempted while stale, then after a fresh update.
        uint256 snap2 = vm.snapshotState();
        vm.warp(vm.getBlockTimestamp() + o.staleSeconds);
        r = _remove(lp, _positionLiquidity(lp) / 2);
        _record(
            Step(
                "ordering_remove_before_update",
                "ordering",
                "oracle_stale",
                "observe",
                false,
                "Removal before the oracle is refreshed"
            ),
            r
        );
        (bool ok, bytes memory ret) = o.oracle.staticcall(abi.encodePacked(o.selector));
        if (ok && ret.length >= 32) {
            int256 answer = o.kind == 2 ? int256(abi.decode(ret, (uint256))) : _chainlinkAnswer(ret);
            vm.mockCall(o.oracle, abi.encodePacked(o.selector), _oracleReturn(o.kind, answer, vm.getBlockTimestamp()));
        }
        r = _remove(lp, _positionLiquidity(lp) / 2);
        _record(
            Step(
                "ordering_remove_after_update",
                "ordering",
                "oracle_refreshed",
                "success",
                false,
                "Removal after the oracle is refreshed"
            ),
            r
        );
        vm.clearMockedCalls();
        vm.revertToState(snap2);
        _finish();
    }

    function _chainlinkAnswer(bytes memory ret) internal pure returns (int256 answer) {
        if (ret.length < 160) return 0;
        (, answer,,,) = abi.decode(ret, (uint80, int256, uint256, uint256, uint80));
    }

    function _applyOracleCondition(OracleConfig memory o, string memory cond) internal returns (bool) {
        bytes32 c = keccak256(bytes(cond));
        if (c == keccak256("oracle_revert")) {
            vm.mockCallRevert(o.oracle, abi.encodePacked(o.selector), bytes("HookLens: mocked oracle revert"));
            return true;
        }
        if (c == keccak256("oracle_zero")) {
            vm.mockCall(o.oracle, abi.encodePacked(o.selector), _oracleReturn(o.kind, 0, vm.getBlockTimestamp()));
            return true;
        }
        if (c == keccak256("oracle_negative")) {
            if (o.kind == 2) return false;
            vm.mockCall(o.oracle, abi.encodePacked(o.selector), _oracleReturn(o.kind, -1, vm.getBlockTimestamp()));
            return true;
        }
        if (c == keccak256("oracle_stale")) {
            vm.warp(vm.getBlockTimestamp() + o.staleSeconds);
            return true;
        }
        if (c == keccak256("oracle_jump_10x")) {
            (bool ok, bytes memory ret) = o.oracle.staticcall(abi.encodePacked(o.selector));
            if (!ok || ret.length < 32) return false;
            int256 answer = o.kind == 2 ? int256(abi.decode(ret, (uint256))) : _chainlinkAnswer(ret);
            vm.mockCall(
                o.oracle, abi.encodePacked(o.selector), _oracleReturn(o.kind, answer * 10, vm.getBlockTimestamp())
            );
            return true;
        }
        return false;
    }

    // ================================================================ S4 accounting

    struct Snapshot {
        int256[2][7] bal; // parties x currencies
    }

    function _parties() internal view returns (address[7] memory p) {
        p = [
            address(lp),
            address(lp2),
            address(trader),
            address(trader2),
            address(manager),
            address(key.hooks),
            address(0)
        ];
    }

    function _snap() internal view returns (Snapshot memory s) {
        address[7] memory p = _parties();
        Currency[2] memory cs = [key.currency0, key.currency1];
        for (uint256 i; i < 6; i++) {
            for (uint256 j; j < 2; j++) {
                s.bal[i][j] = int256(_balanceOf(cs[j], p[i]));
            }
        }
        // ERC6909 claims minted to the hook are a liability of the PoolManager to the hook.
        for (uint256 j; j < 2; j++) {
            s.bal[6][j] = int256(IERC6909Claims(address(manager)).balanceOf(address(key.hooks), cs[j].toId()));
        }
    }

    /// @notice Checks one accounting step. Invariants (protocol-correct, custom-delta aware):
    ///  (1) the acting actor's token balance changes by exactly the delta returned to it;
    ///  (2) value is conserved across the tracked set {actors, PoolManager, hook} — tokens
    ///      leaving that set are reported, not assumed malicious (a hook may forward fees).
    function _checkStep(Step memory s, OpResult memory r, Snapshot memory before, uint256 actorIdx) internal {
        Snapshot memory afterS = _snap();
        int256[2] memory actorChange =
            [afterS.bal[actorIdx][0] - before.bal[actorIdx][0], afterS.bal[actorIdx][1] - before.bal[actorIdx][1]];
        int256[2] memory sum;
        for (uint256 j; j < 2; j++) {
            for (uint256 i; i < 6; i++) {
                sum[j] += afterS.bal[i][j] - before.bal[i][j];
            }
        }
        int256[2] memory claimsChange = [afterS.bal[6][0] - before.bal[6][0], afterS.bal[6][1] - before.bal[6][1]];
        bool actorMatches = !r.ok || (actorChange[0] == r.amount0 && actorChange[1] == r.amount1);
        bool conserved = sum[0] == 0 && sum[1] == 0;
        string memory m = string.concat(
            _metric("actor_change0", actorChange[0]),
            ",",
            _metric("actor_change1", actorChange[1]),
            ",",
            _metric("tracked_sum0", sum[0]),
            ",",
            _metric("tracked_sum1", sum[1]),
            ",",
            _metric("hook_claims_change0", claimsChange[0]),
            ",",
            _metric("hook_claims_change1", claimsChange[1])
        );
        m = string.concat(
            m,
            ",\"actor_delta_matches\":",
            actorMatches ? "true" : "false",
            ",\"value_conserved\":",
            conserved ? "true" : "false"
        );
        _recordWithMetrics(s, r, m);
        if (r.ok && !actorMatches) {
            // Invariant (1) broken: the actor's balance moved by something other than its BalanceDelta.
            _recordRaw(
                Step(
                    string.concat("invariant_", s.name),
                    "invariant",
                    "actor_delta_mismatch",
                    "conserved",
                    false,
                    "The acting account's balance change differs from the BalanceDelta it was given"
                ),
                false,
                "",
                actorChange[0] - r.amount0,
                actorChange[1] - r.amount1,
                0,
                ""
            );
        } else if (r.ok && !conserved) {
            // Invariant (2) is reported, not failed: hooks may forward fees to accounts outside the
            // tracked set {actors, PoolManager, hook}. amount0/amount1 = net change of the tracked set.
            _recordRaw(
                Step(
                    string.concat("outflow_", s.name),
                    "invariant",
                    "value_left_tracked_set",
                    "observe",
                    false,
                    "Tokens moved between the tracked set and other accounts (e.g. hook fee forwarding); the actor's balance still matched its delta"
                ),
                true,
                "",
                sum[0],
                sum[1],
                0,
                ""
            );
        }
    }

    function _runAccounting() internal {
        _begin("accounting_invariants");
        if (_abortIfInfraError()) return;
        Snapshot memory b;
        OpResult memory r;

        b = _snap();
        r = _add(lp, liquidity);
        _checkStep(Step("lp1_add", "liquidity", "baseline", "success", false, "LP1 adds liquidity"), r, b, 0);

        b = _snap();
        r = lp2.modify(key, tickLower + key.tickSpacing * 10, tickUpper - key.tickSpacing * 10, int256(liquidity / 2));
        _checkStep(
            Step("lp2_add_narrow", "liquidity", "baseline", "success", false, "LP2 adds a narrower position"), r, b, 1
        );

        b = _snap();
        r = _swapExactIn(trader, true, swapAmount);
        _checkStep(Step("exact_in_0_for_1", "swap", "baseline", "success", false, "Exact-input swap"), r, b, 2);

        b = _snap();
        r = _swapExactOut(trader2, false, _out(false) / 2);
        _checkStep(Step("exact_out_1_for_0", "swap", "baseline", "success", false, "Exact-output swap"), r, b, 3);
        if (r.ok) {
            _recordRaw(
                Step(
                    "exact_out_amount_delivered", "swap", "baseline", "observe", false, "Output received vs requested"
                ),
                r.amount0 == int256(_out(false) / 2),
                "",
                r.amount0,
                int256(_out(false) / 2),
                0,
                ""
            );
        }

        b = _snap();
        r = _swapExactIn(trader, false, swapAmount1);
        _checkStep(Step("exact_in_1_for_0", "swap", "baseline", "success", false, "Exact-input swap"), r, b, 2);

        b = _snap();
        r = _swapExactOut(trader2, true, _out(true) / 2);
        _checkStep(Step("exact_out_0_for_1", "swap", "baseline", "success", false, "Exact-output swap"), r, b, 3);

        for (uint256 k; k < 3; k++) {
            b = _snap();
            r = _swapExactIn(trader, k % 2 == 0, _in(k % 2 == 0) / 3);
            _checkStep(
                Step(
                    string.concat("repeated_swap_", vm.toString(k)),
                    "swap",
                    "baseline",
                    "success",
                    false,
                    "Repeated swap"
                ),
                r,
                b,
                2
            );
        }

        b = _snap();
        r = _remove(lp, _positionLiquidity(lp));
        _checkStep(Step("lp1_remove_all", "liquidity", "baseline", "success", false, "LP1 removes everything"), r, b, 0);

        b = _snap();
        r = lp2.modify(key, tickLower + key.tickSpacing * 10, tickUpper - key.tickSpacing * 10, -int256(liquidity / 2));
        _checkStep(Step("lp2_remove_all", "liquidity", "baseline", "success", false, "LP2 removes everything"), r, b, 1);

        _finish();
    }

    // ================================================================ S5 admin / upgrade

    function _runAdmin(AdminConfig memory cfg) internal {
        _begin("admin_upgrade");
        if (_abortIfInfraError()) return;

        for (uint256 i; i < cfg.calls.length; i++) {
            uint256 snap = vm.snapshotState();
            (bool ok, bytes memory ret) = outsider.tryCall(address(key.hooks), cfg.calls[i]);
            _recordRaw(
                Step(
                    string.concat("unauthorized_", _label(cfg.labels, i, "admin_call")),
                    "unauthorized",
                    "unprivileged_caller",
                    "revert",
                    false,
                    "Privileged function called by an account with no role"
                ),
                ok,
                ret,
                0,
                0,
                0,
                ""
            );
            vm.revertToState(snap);
            if (hookOwner != address(0)) {
                (ok, ret) = _privilegedCall(hookOwner, address(key.hooks), cfg.calls[i]);
                _recordRaw(
                    Step(
                        string.concat("authorized_", _label(cfg.labels, i, "admin_call")),
                        "authorized",
                        "privileged_owner",
                        "observe",
                        true,
                        "Expected privileged behaviour (impersonated in the fork only)"
                    ),
                    ok,
                    ret,
                    0,
                    0,
                    0,
                    ""
                );
                vm.revertToState(snap);
            }
        }

        if (cfg.upgradeSelector != bytes4(0)) {
            OpResult memory r = _add(lp, liquidity);
            _record(
                Step(
                    "add_before_upgrade",
                    "upgrade",
                    "baseline",
                    "success",
                    false,
                    "LP adds liquidity before any upgrade"
                ),
                r
            );
            RevertingImplementation impl = new RevertingImplementation();
            bytes memory call = abi.encodeWithSelector(cfg.upgradeSelector, address(impl));
            (bool ok, bytes memory ret) = outsider.tryCall(address(key.hooks), call);
            _recordRaw(
                Step(
                    "unauthorized_upgrade",
                    "upgrade",
                    "unprivileged_caller",
                    "revert",
                    false,
                    "Upgrade attempted by an account with no role"
                ),
                ok,
                ret,
                0,
                0,
                0,
                ""
            );
            if (cfg.proxyAdmin != address(0)) {
                (ok, ret) = _privilegedCall(cfg.proxyAdmin, address(key.hooks), call);
                _recordRaw(
                    Step(
                        "authorized_upgrade_to_reverting_impl",
                        "upgrade",
                        "privileged_admin",
                        "observe",
                        true,
                        "Proxy admin upgrades to an implementation whose callbacks revert"
                    ),
                    ok,
                    ret,
                    0,
                    0,
                    0,
                    ""
                );
                if (ok) {
                    r = _remove(lp, _positionLiquidity(lp));
                    _record(
                        Step(
                            "remove_after_upgrade",
                            "upgrade",
                            "upgraded_implementation",
                            "success",
                            true,
                            "LP removal after an authorized upgrade"
                        ),
                        r
                    );
                }
            }
        }
        _finish();
    }

    // ================================================================ S6 transaction ordering

    function _runOrdering() internal {
        _begin("transaction_ordering");
        if (_abortIfInfraError()) return;
        OpResult memory r = _add(lp2, liquidity);
        _record(Step("seed_liquidity", "setup", "baseline", "success", false, "Background LP liquidity"), r);

        uint256 snap = vm.snapshotState();
        r = _swapExactIn(trader, true, swapAmount);
        _record(
            Step("single_large_swap", "split_vs_single", "single", "observe", false, "One swap of the full amount"), r
        );
        int256 singleOut = r.amount1;
        vm.revertToState(snap);

        snap = vm.snapshotState();
        OpResult memory a = _swapExactIn(trader, true, swapAmount / 2);
        OpResult memory b = _swapExactIn(trader, true, swapAmount - swapAmount / 2);
        _recordRaw(
            Step(
                "split_two_swaps", "split_vs_single", "split", "observe", false, "Two swaps summing to the same input"
            ),
            a.ok && b.ok,
            a.ok ? b.revertData : a.revertData,
            a.amount0 + b.amount0,
            a.amount1 + b.amount1,
            a.gasUsed + b.gasUsed,
            string.concat(
                _metric("single_swap_output1", singleOut),
                ",",
                _metric("split_minus_single_output1", (a.amount1 + b.amount1) - singleOut)
            )
        );
        vm.revertToState(snap);

        // LP joins before vs after a swap: measured difference in tokens returned on exit.
        snap = vm.snapshotState();
        r = _add(lp, liquidity);
        _swapExactIn(trader, true, swapAmount);
        _swapExactIn(trader, false, swapAmount1);
        OpResult memory exitBefore = _remove(lp, _positionLiquidity(lp));
        _record(
            Step(
                "lp_added_before_swaps_exit",
                "liquidity_ordering",
                "add_then_swap",
                "success",
                false,
                "LP exit after swaps occurred while in range"
            ),
            exitBefore
        );
        vm.revertToState(snap);

        snap = vm.snapshotState();
        _swapExactIn(trader, true, swapAmount);
        _swapExactIn(trader, false, swapAmount1);
        r = _add(lp, liquidity);
        OpResult memory exitAfter = _remove(lp, _positionLiquidity(lp));
        _record(
            Step(
                "lp_added_after_swaps_exit",
                "liquidity_ordering",
                "swap_then_add",
                "success",
                false,
                "LP exit when swaps happened before joining"
            ),
            exitAfter
        );
        vm.revertToState(snap);

        // Round trips: repeated back-and-forth swaps by one trader.
        snap = vm.snapshotState();
        int256 net0;
        int256 net1;
        bool allOk = true;
        for (uint256 k; k < 4; k++) {
            OpResult memory x = _swapExactIn(trader, k % 2 == 0, _in(k % 2 == 0) / 4);
            allOk = allOk && x.ok;
            net0 += x.amount0;
            net1 += x.amount1;
        }
        _recordRaw(
            Step(
                "round_trip_swaps",
                "repeated",
                "baseline",
                "observe",
                false,
                "Net trader position after four alternating swaps"
            ),
            allOk,
            "",
            net0,
            net1,
            0,
            ""
        );
        vm.revertToState(snap);
        _finish();
    }
}
