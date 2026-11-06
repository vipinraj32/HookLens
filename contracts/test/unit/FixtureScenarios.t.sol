// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {PoolManager} from "@uniswap/v4-core/src/PoolManager.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {FixtureDeployer} from "../../src/harness/FixtureDeployer.sol";
import {DynamicFeeHook} from "../../src/fixtures/DynamicFeeHook.sol";
import {PausableAdminHook} from "../../src/fixtures/PausableAdminHook.sol";
import {HookProxy} from "../../src/fixtures/HookProxy.sol";
import {Scenarios} from "../harness/Scenarios.sol";

/// @notice Runs the HookLens scenario harness against locally deployed fixture hooks whose
///         behaviour is known by construction, and asserts that the harness observes it.
///         This validates the harness itself; it says nothing about third-party hooks.
abstract contract FixtureScenarioTest is Scenarios, FixtureDeployer {
    Fixtures internal fx;

    function _deploy() internal {
        IPoolManager m = IPoolManager(address(new PoolManager(address(this))));
        fx = _deployFixtures(m, address(this), address(this));
        _seedPools(fx, address(this));
    }

    function _use(PoolKey memory k, string memory name) internal {
        // 0.001 hlWETH (18 decimals) is value-comparable to 2 hlUSD (6 decimals) at the seed price.
        bool wethIs0 = address(fx.weth) < address(fx.usdc);
        (uint256 amt0, uint256 amt1) = wethIs0 ? (uint256(1e15), uint256(2e6)) : (uint256(2e6), uint256(1e15));
        _configure(fx.manager, k, address(this), 1e12, amt0, amt1);
        outDir = string.concat("sim-out/unit/", name);
    }

    function _assertStep(string memory name, bool expectedOk) internal {
        (bool found, bool ok) = _stepResult(name);
        assertTrue(found, string.concat("step not recorded: ", name));
        assertEq(ok, expectedOk, string.concat("unexpected outcome for step: ", name));
    }
}

contract OracleGatedFixtureTest is FixtureScenarioTest {
    function setUp() public {
        _deploy();
        _use(fx.oracleGatedKey, "oracle_gated");
    }

    function test_withdrawalBlockedByOracleConditions() public {
        WithdrawalConfig memory cfg;
        cfg.conditions = new string[](4);
        cfg.conditions[0] = "oracle_revert";
        cfg.conditions[1] = "oracle_zero";
        cfg.conditions[2] = "oracle_stale";
        cfg.conditions[3] = "paused";
        cfg.oracle = OracleConfig(address(fx.oracle), bytes4(0xfeaf968c), 1, 7 days);
        _runWithdrawal(cfg);

        _assertStep("partial_remove_50pct", true);
        _assertStep("full_remove", true);
        _assertStep("remove_under_oracle_revert", false);
        _assertStep("recover_after_oracle_revert", true);
        _assertStep("remove_under_oracle_zero", false);
        _assertStep("remove_under_oracle_stale", false);
        _assertStep("recover_after_oracle_stale", true);
        // No pause function was configured: recorded as not applicable, not as a failure.
        _assertStep("condition_paused", false);
    }

    function test_oracleFailureMatrix() public {
        _runOracleFailure(OracleConfig(address(fx.oracle), bytes4(0xfeaf968c), 1, 7 days));
        _assertStep("swap_under_oracle_revert", true); // swaps do not consult the oracle
        _assertStep("remove_under_oracle_revert", false);
        _assertStep("remove_under_oracle_negative", false);
        _assertStep("remove_under_oracle_jump_10x", true); // no deviation check in this hook
        _assertStep("ordering_remove_before_update", false);
        _assertStep("ordering_remove_after_update", true);
    }
}

contract PausableFixtureTest is FixtureScenarioTest {
    function setUp() public {
        _deploy();
        _use(fx.pausableKey, "pausable");
    }

    function test_pauseBlocksWithdrawalUntilOwnerActs() public {
        WithdrawalConfig memory cfg;
        cfg.conditions = new string[](1);
        cfg.conditions[0] = "paused";
        cfg.pauseCall = abi.encodeCall(PausableAdminHook.pause, ());
        _runWithdrawal(cfg);
        _assertStep("remove_under_paused", false);
        _assertStep("recover_after_paused", false);
    }

    function test_adminAndUpgrade() public {
        AdminConfig memory cfg;
        cfg.calls = new bytes[](2);
        cfg.calls[0] = abi.encodeCall(PausableAdminHook.pause, ());
        cfg.calls[1] = abi.encodeCall(PausableAdminHook.transferOwnership, (address(0xBEEF)));
        cfg.labels = new string[](2);
        cfg.labels[0] = "pause";
        cfg.labels[1] = "transferOwnership";
        cfg.upgradeSelector = HookProxy.upgradeTo.selector;
        cfg.proxyAdmin = address(this);
        _runAdmin(cfg);
        _assertStep("unauthorized_pause", false);
        _assertStep("authorized_pause", true);
        _assertStep("unauthorized_transferOwnership", false);
        _assertStep("unauthorized_upgrade", false);
        _assertStep("authorized_upgrade_to_reverting_impl", true);
        _assertStep("remove_after_upgrade", false);
    }
}

contract DynamicFeeFixtureTest is FixtureScenarioTest {
    function setUp() public {
        _deploy();
        _use(fx.dynamicFeeKey, "dynamic_fee");
    }

    function test_feeEscalationToProtocolMaximum() public {
        FeeConfig memory cfg;
        cfg.setterCalls = new bytes[](3);
        cfg.setterCalls[0] = abi.encodeCall(DynamicFeeHook.setFee, (uint24(1_000_000)));
        cfg.setterCalls[1] = abi.encodeCall(DynamicFeeHook.setMaxFee, (uint24(1_000_000)));
        cfg.setterCalls[2] = abi.encodeCall(DynamicFeeHook.setFee, (uint24(1_000_000)));
        cfg.setterLabels = new string[](3);
        cfg.setterLabels[0] = "setFee_1000000_initial";
        cfg.setterLabels[1] = "setMaxFee_1000000";
        cfg.setterLabels[2] = "setFee_1000000";
        _runFeeEscalation(cfg);
        _assertStep("baseline_swap_0_for_1", true);
        _assertStep("unauthorized_setFee_1000000_initial", false);
        _assertStep("authorized_setFee_1000000_initial", false); // bounded by maxFee
        _assertStep("authorized_setMaxFee_1000000", true);
        _assertStep("authorized_setFee_1000000", true);
        _assertStep("swap_after_setFee_1000000", true);
        assertEq(DynamicFeeHook(fx.dynamicFeeHook).fee(), 1_000_000, "authorized sequence applied");
    }
}

contract SwapFeeDeltaFixtureTest is FixtureScenarioTest {
    function setUp() public {
        _deploy();
        _use(fx.swapFeeDeltaKey, "swap_fee_delta");
    }

    function test_accountingConservedWithCustomDelta() public {
        _runAccounting();
        _assertStep("lp1_add", true);
        _assertStep("exact_in_0_for_1", true);
        _assertStep("exact_out_1_for_0", true);
        _assertStep("lp1_remove_all", true);
        (bool found,) = _stepResult("invariant_exact_in_0_for_1");
        assertFalse(found, "custom-delta hook must not trip the conservation invariant");
        (found,) = _stepResult("outflow_exact_in_0_for_1");
        assertFalse(found, "the fixture keeps its fee inside the tracked set");
    }
}

contract NoOpFixtureTest is FixtureScenarioTest {
    function setUp() public {
        _deploy();
        _use(fx.noOpKey, "noop");
    }

    function test_orderingScenarioRuns() public {
        _runOrdering();
        _assertStep("single_large_swap", true);
        _assertStep("split_two_swaps", true);
        _assertStep("lp_added_before_swaps_exit", true);
        _assertStep("lp_added_after_swaps_exit", true);
    }

    function test_accountingBaseline() public {
        _runAccounting();
        (bool found,) = _stepResult("invariant_lp1_remove_all");
        assertFalse(found, "baseline hook accounting must be conserved");
        (found,) = _stepResult("outflow_exact_in_0_for_1");
        assertFalse(found, "no value leaves the tracked set for a no-op hook");
    }
}
