// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {SwapParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";

/// @notice HOOKLENS CLI TEST FIXTURE (candidate): implements a v4-shaped callback without inheriting
///         IHooks, so HookLens can only label it a candidate with low confidence.
contract CandidateHook {
    uint256 public calls;

    function beforeSwap(address, PoolKey calldata, SwapParams calldata, bytes calldata) external returns (bytes4) {
        calls++;
        return this.beforeSwap.selector;
    }
}
