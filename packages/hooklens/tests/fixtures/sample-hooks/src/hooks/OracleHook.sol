// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "@uniswap/v4-core/src/types/BeforeSwapDelta.sol";
import {SwapParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {MiniBaseHook} from "../base/MiniBaseHook.sol";
import {IPriceFeed} from "../interfaces/IPriceFeed.sol";

/// @notice HOOKLENS CLI TEST FIXTURE (oracle-dependent hook): every swap reads an owner-replaceable feed.
contract OracleHook is MiniBaseHook {
    error StalePrice();

    address public owner;
    IPriceFeed public feed;

    constructor(IPoolManager _pm, IPriceFeed _feed) MiniBaseHook(_pm) {
        owner = msg.sender;
        feed = _feed;
    }

    function setFeed(IPriceFeed newFeed) external {
        require(msg.sender == owner, "not owner");
        feed = newFeed;
    }

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.beforeSwap = true;
    }

    function _beforeSwap(address, PoolKey calldata, SwapParams calldata, bytes calldata)
        internal
        view
        override
        returns (bytes4, BeforeSwapDelta, uint24)
    {
        (, int256 answer,, uint256 updatedAt,) = feed.latestRoundData();
        if (answer <= 0 || block.timestamp - updatedAt > 1 hours) revert StalePrice();
        return (this.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, 0);
    }
}
