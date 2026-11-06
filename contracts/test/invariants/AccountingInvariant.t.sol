// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Test} from "forge-std/Test.sol";
import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {PoolManager} from "@uniswap/v4-core/src/PoolManager.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {PoolIdLibrary} from "@uniswap/v4-core/src/types/PoolId.sol";
import {Currency} from "@uniswap/v4-core/src/types/Currency.sol";
import {IERC20Minimal} from "@uniswap/v4-core/src/interfaces/external/IERC20Minimal.sol";
import {StateLibrary} from "@uniswap/v4-core/src/libraries/StateLibrary.sol";
import {PoolModifyLiquidityTestNoChecks} from "@uniswap/v4-core/src/test/PoolModifyLiquidityTestNoChecks.sol";
import {PoolSwapTest} from "@uniswap/v4-core/src/test/PoolSwapTest.sol";
import {FixtureDeployer} from "../../src/harness/FixtureDeployer.sol";
import {LPActor, TraderActor, OpResult} from "../../src/harness/Actors.sol";

/// @notice Stateful fuzz handler: random adds, removes and swaps by several actors against the
///         SwapFeeDeltaHook pool (custom afterSwap return delta).
contract AccountingHandler is Test {
    using StateLibrary for IPoolManager;
    using PoolIdLibrary for PoolKey;

    IPoolManager public manager;
    PoolKey public key;
    LPActor[2] public lps;
    TraderActor[2] public traders;
    int24 public lower;
    int24 public upper;
    uint256 public hookFeeTaken0;
    uint256 public hookFeeTaken1;
    uint256 public calls;

    constructor(IPoolManager _m, PoolKey memory _k, PoolModifyLiquidityTestNoChecks lr, PoolSwapTest sr, int24 tick) {
        manager = _m;
        key = _k;
        lower = tick - 3000;
        upper = tick + 3000;
        for (uint256 i; i < 2; i++) {
            lps[i] = new LPActor(lr);
            traders[i] = new TraderActor(sr);
            address[2] memory who = [address(lps[i]), address(traders[i])];
            for (uint256 j; j < 2; j++) {
                deal(Currency.unwrap(_k.currency0), who[j], 1e30);
                deal(Currency.unwrap(_k.currency1), who[j], 1e30);
            }
            lps[i].approve(_k);
            traders[i].approve(_k);
        }
    }

    function add(uint256 who, uint256 liq) external {
        liq = bound(liq, 1e6, 1e13);
        lps[who % 2].modify(key, lower, upper, int256(liq));
        calls++;
    }

    function remove(uint256 who, uint256 pct) external {
        LPActor a = lps[who % 2];
        (uint128 liq,,) = manager.getPositionInfo(key.toId(), address(a.router()), lower, upper, a.positionSalt());
        if (liq == 0) return;
        uint256 amt = uint256(liq) * bound(pct, 1, 100) / 100;
        if (amt == 0) return;
        a.modify(key, lower, upper, -int256(amt));
        calls++;
    }

    function swap(uint256 who, bool zeroForOne, uint256 amount, bool exactIn) external {
        amount = bound(amount, 1e3, 1e14);
        address hook = address(key.hooks);
        uint256 h0 = IERC20Minimal(Currency.unwrap(key.currency0)).balanceOf(hook);
        uint256 h1 = IERC20Minimal(Currency.unwrap(key.currency1)).balanceOf(hook);
        traders[who % 2].swap(key, zeroForOne, exactIn ? -int256(amount) : int256(amount));
        hookFeeTaken0 += IERC20Minimal(Currency.unwrap(key.currency0)).balanceOf(hook) - h0;
        hookFeeTaken1 += IERC20Minimal(Currency.unwrap(key.currency1)).balanceOf(hook) - h1;
        calls++;
    }
}

/// @notice Invariants for a custom-delta hook pool:
///  - token conservation across the closed set {seeder, handler actors, PoolManager, hook};
///  - the hook only gains tokens through swaps (ghost-tracked), never loses them;
///  - the PoolManager never ends a transaction with a negative balance (implicit: transfers revert).
contract AccountingInvariantTest is Test, FixtureDeployer {
    Fixtures internal fx;
    AccountingHandler internal handler;
    uint256 internal total0;
    uint256 internal total1;

    function setUp() public {
        IPoolManager m = IPoolManager(address(new PoolManager(address(this))));
        fx = _deployFixtures(m, address(this), address(this));
        _seedPools(fx, address(this));
        handler = new AccountingHandler(m, fx.swapFeeDeltaKey, fx.lpRouter, fx.swapRouter, fx.initialTick);
        total0 = _sum(fx.swapFeeDeltaKey.currency0);
        total1 = _sum(fx.swapFeeDeltaKey.currency1);
        targetContract(address(handler));
    }

    function _parties() internal view returns (address[7] memory p) {
        p = [
            address(this),
            address(fx.manager),
            fx.swapFeeDeltaHook,
            address(handler.lps(0)),
            address(handler.lps(1)),
            address(handler.traders(0)),
            address(handler.traders(1))
        ];
    }

    function _sum(Currency c) internal view returns (uint256 s) {
        address[7] memory p = _parties();
        for (uint256 i; i < p.length; i++) {
            s += IERC20Minimal(Currency.unwrap(c)).balanceOf(p[i]);
        }
    }

    function invariant_tokenConservation() public view {
        assertEq(_sum(fx.swapFeeDeltaKey.currency0), total0, "currency0 left the closed set");
        assertEq(_sum(fx.swapFeeDeltaKey.currency1), total1, "currency1 left the closed set");
    }

    function invariant_hookBalanceEqualsGhostFees() public view {
        assertEq(
            IERC20Minimal(Currency.unwrap(fx.swapFeeDeltaKey.currency0)).balanceOf(fx.swapFeeDeltaHook),
            handler.hookFeeTaken0()
        );
        assertEq(
            IERC20Minimal(Currency.unwrap(fx.swapFeeDeltaKey.currency1)).balanceOf(fx.swapFeeDeltaHook),
            handler.hookFeeTaken1()
        );
    }
}
