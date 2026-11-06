// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "@uniswap/v4-core/src/types/BeforeSwapDelta.sol";
import {ModifyLiquidityParams, SwapParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {FixtureBaseHook} from "./FixtureBaseHook.sol";

/// @title PausableAdminHook
/// @notice HOOKLENS TEST FIXTURE. Upgradeable (deployed behind HookProxy) hook whose owner
///         can pause swaps, liquidity additions AND liquidity removals. While paused, LPs
///         cannot withdraw. Storage is initialised through `initialize` (proxy pattern).
contract PausableAdminHook is FixtureBaseHook {
    error NotOwner();
    error AlreadyInitialized();
    error Paused();

    event PauseSet(bool paused);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    address public owner;
    bool public paused;
    bool private initialized;

    constructor(IPoolManager _poolManager) FixtureBaseHook(_poolManager, false) {}

    function initialize(address _owner) external {
        if (initialized) revert AlreadyInitialized();
        initialized = true;
        owner = _owner;
        emit OwnershipTransferred(address(0), _owner);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier whenNotPaused() {
        if (paused) revert Paused();
        _;
    }

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.beforeAddLiquidity = true;
        p.beforeRemoveLiquidity = true;
        p.beforeSwap = true;
    }

    function pause() external onlyOwner {
        paused = true;
        emit PauseSet(true);
    }

    function unpause() external onlyOwner {
        paused = false;
        emit PauseSet(false);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function beforeAddLiquidity(address, PoolKey calldata, ModifyLiquidityParams calldata, bytes calldata)
        external
        view
        override
        onlyPoolManager
        whenNotPaused
        returns (bytes4)
    {
        return this.beforeAddLiquidity.selector;
    }

    function beforeRemoveLiquidity(address, PoolKey calldata, ModifyLiquidityParams calldata, bytes calldata)
        external
        view
        override
        onlyPoolManager
        whenNotPaused
        returns (bytes4)
    {
        return this.beforeRemoveLiquidity.selector;
    }

    function beforeSwap(address, PoolKey calldata, SwapParams calldata, bytes calldata)
        external
        view
        override
        onlyPoolManager
        whenNotPaused
        returns (bytes4, BeforeSwapDelta, uint24)
    {
        return (this.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, 0);
    }
}
