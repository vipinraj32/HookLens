// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {ModifyLiquidityParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {MiniBaseHook} from "../base/MiniBaseHook.sol";

/// @notice HOOKLENS CLI TEST FIXTURE (withdrawal failure pattern): the owner can freeze all liquidity
///         removal until an arbitrary timestamp. The check lives in the internal `_beforeRemoveLiquidity`
///         override, so finding it requires following virtual dispatch from the base hook.
contract WithdrawalLockHook is MiniBaseHook {
    error WithdrawalsLocked();

    address public owner;
    uint256 public unlockTime;

    constructor(IPoolManager _pm) MiniBaseHook(_pm) {
        owner = msg.sender;
    }

    function lockUntil(uint256 timestamp) external {
        require(msg.sender == owner, "not owner");
        unlockTime = timestamp;
    }

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.beforeRemoveLiquidity = true;
    }

    function _beforeRemoveLiquidity(address, PoolKey calldata, ModifyLiquidityParams calldata, bytes calldata)
        internal
        view
        override
        returns (bytes4)
    {
        if (block.timestamp < unlockTime) revert WithdrawalsLocked();
        return this.beforeRemoveLiquidity.selector;
    }
}
