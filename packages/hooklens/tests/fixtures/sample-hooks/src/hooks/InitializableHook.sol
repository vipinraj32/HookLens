// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {ModifyLiquidityParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {MiniBaseHook} from "../base/MiniBaseHook.sol";

/// @notice HOOKLENS CLI TEST FIXTURE (implementation behind HookProxy): initializer without a caller
///         check, and an owner pause that gates liquidity removal.
contract InitializableHook is MiniBaseHook {
    error Paused();

    address public owner;
    bool public paused;
    bool private initialized;

    constructor(IPoolManager _pm) MiniBaseHook(_pm) {}

    function initialize(address _owner) external {
        require(!initialized, "initialized");
        initialized = true;
        owner = _owner;
    }

    function setPaused(bool value) external {
        require(msg.sender == owner, "not owner");
        paused = value;
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
        if (paused) revert Paused();
        return this.beforeRemoveLiquidity.selector;
    }
}
