// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {SafeCast} from "@uniswap/v4-core/src/libraries/SafeCast.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {BalanceDelta} from "@uniswap/v4-core/src/types/BalanceDelta.sol";
import {Currency} from "@uniswap/v4-core/src/types/Currency.sol";
import {SwapParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {FixtureBaseHook} from "./FixtureBaseHook.sol";

/// @title SwapFeeDeltaHook
/// @notice HOOKLENS TEST FIXTURE. Takes an owner-configurable cut of the unspecified side of
///         every swap through afterSwapReturnDelta. The cut is paid by traders (not LPs) and
///         is taken out of the PoolManager, so accounting must include the hook balance.
///         Modelled on the v4-core FeeTakingHook test contract.
contract SwapFeeDeltaHook is FixtureBaseHook {
    using SafeCast for uint256;

    error NotOwner();
    error FeeTooHigh(uint256 bips, uint256 cap);

    event HookFeeUpdated(uint256 oldBips, uint256 newBips);

    uint256 public constant TOTAL_BIPS = 10_000;
    uint256 public constant MAX_HOOK_FEE_BIPS = 500; // 5%

    address public owner;
    uint256 public hookFeeBips;

    constructor(IPoolManager _poolManager, address _owner, uint256 _bips) FixtureBaseHook(_poolManager, true) {
        if (_bips > MAX_HOOK_FEE_BIPS) revert FeeTooHigh(_bips, MAX_HOOK_FEE_BIPS);
        owner = _owner;
        hookFeeBips = _bips;
    }

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.afterSwap = true;
        p.afterSwapReturnDelta = true;
    }

    function setHookFeeBips(uint256 newBips) external {
        if (msg.sender != owner) revert NotOwner();
        if (newBips > MAX_HOOK_FEE_BIPS) revert FeeTooHigh(newBips, MAX_HOOK_FEE_BIPS);
        emit HookFeeUpdated(hookFeeBips, newBips);
        hookFeeBips = newBips;
    }

    function afterSwap(address, PoolKey calldata key, SwapParams calldata params, BalanceDelta delta, bytes calldata)
        external
        override
        onlyPoolManager
        returns (bytes4, int128)
    {
        bool specifiedTokenIs0 = (params.amountSpecified < 0 == params.zeroForOne);
        (Currency feeCurrency, int128 swapAmount) =
            specifiedTokenIs0 ? (key.currency1, delta.amount1()) : (key.currency0, delta.amount0());
        if (swapAmount < 0) swapAmount = -swapAmount;
        uint256 feeAmount = uint128(swapAmount) * hookFeeBips / TOTAL_BIPS;
        if (feeAmount > 0) poolManager.take(feeCurrency, address(this), feeAmount);
        return (this.afterSwap.selector, feeAmount.toInt128());
    }
}
