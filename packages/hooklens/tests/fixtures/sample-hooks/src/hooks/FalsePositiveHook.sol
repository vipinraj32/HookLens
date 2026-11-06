// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {ModifyLiquidityParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {MiniBaseHook} from "../base/MiniBaseHook.sol";

/// @notice HOOKLENS CLI TEST FIXTURE (false-positive guard): looks risky at a glance but is not.
///         * It has an owner and an owner-only setter, but the variable it sets is never read by a callback.
///         * Its remove-liquidity callback only checks the PoolManager caller and records a counter;
///           it can never block a withdrawal.
///         HookLens must not report withdrawal-blocking or callback-influencing admin findings here.
contract FalsePositiveHook is MiniBaseHook {
    address public owner;
    address public treasury; // admin bookkeeping only; unrelated to pool operations
    uint256 public removals;

    constructor(IPoolManager _pm) MiniBaseHook(_pm) {
        owner = msg.sender;
    }

    function setTreasury(address newTreasury) external {
        require(msg.sender == owner, "not owner");
        treasury = newTreasury;
    }

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.afterRemoveLiquidity = false;
        p.beforeRemoveLiquidity = true;
    }

    function _beforeRemoveLiquidity(address, PoolKey calldata, ModifyLiquidityParams calldata, bytes calldata)
        internal
        override
        returns (bytes4)
    {
        unchecked {
            removals++;
        }
        return this.beforeRemoveLiquidity.selector;
    }
}
