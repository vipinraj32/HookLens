// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Test} from "forge-std/Test.sol";
import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {IHooks} from "@uniswap/v4-core/src/interfaces/IHooks.sol";
import {PoolManager} from "@uniswap/v4-core/src/PoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {LPFeeLibrary} from "@uniswap/v4-core/src/libraries/LPFeeLibrary.sol";
import {FixtureDeployer} from "../../src/harness/FixtureDeployer.sol";
import {DynamicFeeHook} from "../../src/fixtures/DynamicFeeHook.sol";
import {PausableAdminHook} from "../../src/fixtures/PausableAdminHook.sol";
import {HookProxy} from "../../src/fixtures/HookProxy.sol";
import {SwapFeeDeltaHook} from "../../src/fixtures/SwapFeeDeltaHook.sol";
import {MockOracle} from "../../src/fixtures/MockOracle.sol";
import {FixtureBaseHook} from "../../src/fixtures/FixtureBaseHook.sol";
import {SwapParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {BalanceDelta} from "@uniswap/v4-core/src/types/BalanceDelta.sol";

/// @notice Unit and fuzz tests for the fixture hooks themselves.
contract FixtureHooksTest is Test, FixtureDeployer {
    Fixtures internal fx;

    function setUp() public {
        IPoolManager m = IPoolManager(address(new PoolManager(address(this))));
        fx = _deployFixtures(m, address(this), address(this));
        _seedPools(fx, address(this));
    }

    function test_addressBitsEncodeDeclaredPermissions() public view {
        assertEq(uint160(fx.dynamicFeeHook) & Hooks.ALL_HOOK_MASK, Hooks.BEFORE_INITIALIZE_FLAG | Hooks.BEFORE_SWAP_FLAG);
        assertEq(uint160(fx.oracleGatedHook) & Hooks.ALL_HOOK_MASK, Hooks.BEFORE_REMOVE_LIQUIDITY_FLAG);
        assertEq(
            uint160(fx.pausableHookProxy) & Hooks.ALL_HOOK_MASK,
            Hooks.BEFORE_ADD_LIQUIDITY_FLAG | Hooks.BEFORE_REMOVE_LIQUIDITY_FLAG | Hooks.BEFORE_SWAP_FLAG
        );
        assertEq(
            uint160(fx.swapFeeDeltaHook) & Hooks.ALL_HOOK_MASK,
            Hooks.AFTER_SWAP_FLAG | Hooks.AFTER_SWAP_RETURNS_DELTA_FLAG
        );
        assertEq(uint160(fx.noOpHook) & Hooks.ALL_HOOK_MASK, Hooks.BEFORE_SWAP_FLAG | Hooks.AFTER_SWAP_FLAG);
        assertTrue(Hooks.isValidHookAddress(IHooks(fx.dynamicFeeHook), LPFeeLibrary.DYNAMIC_FEE_FLAG));
    }

    function testFuzz_dynamicFeeBounds(uint24 newFee) public {
        DynamicFeeHook h = DynamicFeeHook(fx.dynamicFeeHook);
        if (newFee < h.minFee() || newFee > h.maxFee()) {
            vm.expectRevert(abi.encodeWithSelector(DynamicFeeHook.FeeOutOfBounds.selector, newFee, h.minFee(), h.maxFee()));
            h.setFee(newFee);
        } else {
            h.setFee(newFee);
            assertEq(h.fee(), newFee);
        }
    }

    function testFuzz_onlyOwnerCanSetFee(address caller, uint24 newFee) public {
        vm.assume(caller != address(this));
        vm.prank(caller);
        vm.expectRevert(DynamicFeeHook.NotOwner.selector);
        DynamicFeeHook(fx.dynamicFeeHook).setFee(newFee);
    }

    function testFuzz_onlyAdminCanUpgrade(address caller) public {
        vm.assume(caller != address(this));
        vm.prank(caller);
        vm.expectRevert(HookProxy.NotAdmin.selector);
        HookProxy(payable(fx.pausableHookProxy)).upgradeTo(address(fx.oracle));
    }

    function test_proxyStorageLayout() public view {
        bytes32 implSlot = vm.load(fx.pausableHookProxy, bytes32(uint256(keccak256("eip1967.proxy.implementation")) - 1));
        bytes32 adminSlot = vm.load(fx.pausableHookProxy, bytes32(uint256(keccak256("eip1967.proxy.admin")) - 1));
        assertEq(address(uint160(uint256(implSlot))), fx.pausableHookImpl);
        assertEq(address(uint160(uint256(adminSlot))), address(this));
        assertEq(PausableAdminHook(fx.pausableHookProxy).owner(), address(this));
    }

    function test_initializeOnlyOnce() public {
        vm.expectRevert(PausableAdminHook.AlreadyInitialized.selector);
        PausableAdminHook(fx.pausableHookProxy).initialize(address(0xdead));
    }

    function testFuzz_swapFeeDeltaCap(uint256 bips) public {
        SwapFeeDeltaHook h = SwapFeeDeltaHook(fx.swapFeeDeltaHook);
        if (bips > h.MAX_HOOK_FEE_BIPS()) {
            vm.expectRevert(abi.encodeWithSelector(SwapFeeDeltaHook.FeeTooHigh.selector, bips, h.MAX_HOOK_FEE_BIPS()));
        }
        h.setHookFeeBips(bips);
    }

    function test_oracleUnavailableReverts() public {
        fx.oracle.setUnavailable(true);
        vm.expectRevert(MockOracle.OracleUnavailable.selector);
        fx.oracle.latestRoundData();
    }

    function test_callbacksRejectNonPoolManager() public {
        vm.expectRevert(FixtureBaseHook.NotPoolManager.selector);
        IHooks(fx.noOpHook).afterSwap(address(this), fx.noOpKey, SwapParams(true, -1, 0), BalanceDelta.wrap(0), "");
    }
}
