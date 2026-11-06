// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {BalanceDelta} from "@uniswap/v4-core/src/types/BalanceDelta.sol";
import {Currency} from "@uniswap/v4-core/src/types/Currency.sol";
import {SwapParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {MiniBaseHook} from "../base/MiniBaseHook.sol";

/// @notice HOOKLENS CLI TEST FIXTURE (return-delta hook): takes 1% of every swap's unspecified amount.
contract ReturnDeltaHook is MiniBaseHook {
    constructor(IPoolManager _pm) MiniBaseHook(_pm) {}

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.afterSwap = true;
        p.afterSwapReturnDelta = true;
    }

    function _afterSwap(address, PoolKey calldata key, SwapParams calldata params, BalanceDelta delta, bytes calldata)
        internal
        override
        returns (bytes4, int128)
    {
        bool specifiedTokenIs0 = (params.amountSpecified < 0 == params.zeroForOne);
        (Currency feeCurrency, int128 amount) =
            specifiedTokenIs0 ? (key.currency1, delta.amount1()) : (key.currency0, delta.amount0());
        if (amount < 0) amount = -amount;
        uint256 feeAmount = uint128(amount) / 100;
        poolManager.take(feeCurrency, address(this), feeAmount);
        return (this.afterSwap.selector, int128(int256(feeAmount)));
    }
}
