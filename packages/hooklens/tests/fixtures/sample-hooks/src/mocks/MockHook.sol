// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {MiniBaseHook} from "../base/MiniBaseHook.sol";

/// @notice HOOKLENS CLI TEST FIXTURE: a mock in mocks/, excluded by the default patterns.
contract MockHook is MiniBaseHook {
    constructor(IPoolManager _pm) MiniBaseHook(_pm) {}

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.beforeSwap = true;
    }
}
