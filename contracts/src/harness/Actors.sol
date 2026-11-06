// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20Minimal} from "@uniswap/v4-core/src/interfaces/external/IERC20Minimal.sol";
import {Currency, CurrencyLibrary} from "@uniswap/v4-core/src/types/Currency.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {BalanceDelta} from "@uniswap/v4-core/src/types/BalanceDelta.sol";
import {ModifyLiquidityParams, SwapParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {TickMath} from "@uniswap/v4-core/src/libraries/TickMath.sol";
import {PoolModifyLiquidityTestNoChecks} from "@uniswap/v4-core/src/test/PoolModifyLiquidityTestNoChecks.sol";
import {PoolSwapTest} from "@uniswap/v4-core/src/test/PoolSwapTest.sol";

/// @notice Result of a single actor operation. `ok == false` carries raw revert data.
struct OpResult {
    bool ok;
    bytes revertData;
    int256 amount0;
    int256 amount1;
    uint256 gasUsed;
}

/// @title ActorBase
/// @notice Capabilities shared by HookLens simulation actors. Actors hold their own token
///         balances, approve the v4-core test routers, and never hold privileged roles.
abstract contract ActorBase {
    string public role;

    receive() external payable {}

    function _approveAll(Currency c, address spender) internal {
        if (!c.isAddressZero()) IERC20Minimal(Currency.unwrap(c)).approve(spender, type(uint256).max);
    }

    function _nativeValue(PoolKey memory key) internal view returns (uint256) {
        return key.currency0.isAddressZero() ? address(this).balance : 0;
    }

    /// @notice Unprivileged arbitrary call, used to test that permissioned functions reject
    ///         callers without a role. The actor holds no role on any contract.
    function tryCall(address target, bytes calldata data) external returns (bool ok, bytes memory ret) {
        (ok, ret) = target.call(data);
    }
}

/// @title LPActor
/// @notice Liquidity provider: adds and removes liquidity through PoolModifyLiquidityTestNoChecks.
///         Positions are keyed by (router, ticks, salt); each LP uses its own address as salt.
contract LPActor is ActorBase {
    PoolModifyLiquidityTestNoChecks public immutable router;

    constructor(PoolModifyLiquidityTestNoChecks _router) {
        router = _router;
        role = "liquidity-provider";
    }

    function approve(PoolKey memory key) external {
        _approveAll(key.currency0, address(router));
        _approveAll(key.currency1, address(router));
    }

    function positionSalt() public view returns (bytes32) {
        return bytes32(uint256(uint160(address(this))));
    }

    function modify(PoolKey memory key, int24 tickLower, int24 tickUpper, int256 liquidityDelta)
        external
        returns (OpResult memory r)
    {
        ModifyLiquidityParams memory p = ModifyLiquidityParams({
            tickLower: tickLower,
            tickUpper: tickUpper,
            liquidityDelta: liquidityDelta,
            salt: positionSalt()
        });
        uint256 g = gasleft();
        try router.modifyLiquidity{value: liquidityDelta > 0 ? _nativeValue(key) : 0}(key, p, "") returns (
            BalanceDelta d
        ) {
            r.ok = true;
            r.amount0 = d.amount0();
            r.amount1 = d.amount1();
        } catch (bytes memory err) {
            r.revertData = err;
        }
        r.gasUsed = g - gasleft();
    }
}

/// @title TraderActor
/// @notice Swapper: executes exact-input or exact-output swaps through PoolSwapTest with the
///         widest price limit, so only the hook and pool liquidity constrain execution.
contract TraderActor is ActorBase {
    PoolSwapTest public immutable router;

    constructor(PoolSwapTest _router) {
        router = _router;
        role = "trader";
    }

    function approve(PoolKey memory key) external {
        _approveAll(key.currency0, address(router));
        _approveAll(key.currency1, address(router));
    }

    function swap(PoolKey memory key, bool zeroForOne, int256 amountSpecified) external returns (OpResult memory r) {
        SwapParams memory p = SwapParams({
            zeroForOne: zeroForOne,
            amountSpecified: amountSpecified,
            sqrtPriceLimitX96: zeroForOne ? TickMath.MIN_SQRT_PRICE + 1 : TickMath.MAX_SQRT_PRICE - 1
        });
        uint256 value = zeroForOne ? _nativeValue(key) : 0;
        uint256 g = gasleft();
        try router.swap{value: value}(key, p, PoolSwapTest.TestSettings({takeClaims: false, settleUsingBurn: false}), "")
        returns (BalanceDelta d) {
            r.ok = true;
            r.amount0 = d.amount0();
            r.amount1 = d.amount1();
        } catch (bytes memory err) {
            r.revertData = err;
        }
        r.gasUsed = g - gasleft();
    }
}

/// @title UnprivilegedActor
/// @notice Holds no tokens and no roles. Only used to call permissioned functions and record
///         whether they correctly reject an unauthorized caller.
contract UnprivilegedActor is ActorBase {
    constructor() {
        role = "unprivileged-caller";
    }
}

/// @title RevertingImplementation
/// @notice Replacement implementation used by the upgrade scenario: every call reverts. It
///         demonstrates what an authorized upgrade to arbitrary logic can do to callbacks.
contract RevertingImplementation {
    error HookLensUpgradedImplementation();

    fallback() external payable {
        revert HookLensUpgradedImplementation();
    }
}
