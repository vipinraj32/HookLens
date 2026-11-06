// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {LPFeeLibrary} from "@uniswap/v4-core/src/libraries/LPFeeLibrary.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "@uniswap/v4-core/src/types/BeforeSwapDelta.sol";
import {SwapParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {FixtureBaseHook} from "./FixtureBaseHook.sol";

/// @title DynamicFeeHook
/// @notice HOOKLENS TEST FIXTURE. Overrides the LP fee on every swap with an owner-configured
///         value. The owner can also raise the upper bound up to the protocol maximum (100%),
///         which is the behaviour the HookLens fee-escalation scenario is designed to surface.
contract DynamicFeeHook is FixtureBaseHook {
    error NotOwner();
    error FeeOutOfBounds(uint24 fee, uint24 minFee, uint24 maxFee);
    error InvalidBounds();
    error MustUseDynamicFee();

    event FeeUpdated(uint24 oldFee, uint24 newFee);
    event MaxFeeUpdated(uint24 oldMaxFee, uint24 newMaxFee);

    address public owner;
    uint24 public fee;
    uint24 public minFee;
    uint24 public maxFee;

    constructor(IPoolManager _poolManager, address _owner, uint24 _fee, uint24 _minFee, uint24 _maxFee)
        FixtureBaseHook(_poolManager, true)
    {
        if (_minFee > _maxFee || _maxFee > LPFeeLibrary.MAX_LP_FEE) revert InvalidBounds();
        if (_fee < _minFee || _fee > _maxFee) revert FeeOutOfBounds(_fee, _minFee, _maxFee);
        owner = _owner;
        fee = _fee;
        minFee = _minFee;
        maxFee = _maxFee;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.beforeInitialize = true;
        p.beforeSwap = true;
    }

    /// @notice Set the LP fee (hundredths of a bip) applied to subsequent swaps.
    function setFee(uint24 newFee) external onlyOwner {
        if (newFee < minFee || newFee > maxFee) revert FeeOutOfBounds(newFee, minFee, maxFee);
        emit FeeUpdated(fee, newFee);
        fee = newFee;
    }

    /// @notice Raise or lower the maximum fee. Bounded only by the protocol maximum.
    function setMaxFee(uint24 newMaxFee) external onlyOwner {
        if (newMaxFee < minFee || newMaxFee > LPFeeLibrary.MAX_LP_FEE) revert InvalidBounds();
        emit MaxFeeUpdated(maxFee, newMaxFee);
        maxFee = newMaxFee;
    }

    function beforeInitialize(address, PoolKey calldata key, uint160)
        external
        view
        override
        onlyPoolManager
        returns (bytes4)
    {
        if (!LPFeeLibrary.isDynamicFee(key.fee)) revert MustUseDynamicFee();
        return this.beforeInitialize.selector;
    }

    function beforeSwap(address, PoolKey calldata, SwapParams calldata, bytes calldata)
        external
        view
        override
        onlyPoolManager
        returns (bytes4, BeforeSwapDelta, uint24)
    {
        return (this.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, fee | LPFeeLibrary.OVERRIDE_FEE_FLAG);
    }
}
