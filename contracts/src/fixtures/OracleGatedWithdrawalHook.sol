// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {ModifyLiquidityParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {FixtureBaseHook} from "./FixtureBaseHook.sol";

interface IAggregatorLike {
    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80);
}

/// @title OracleGatedWithdrawalHook
/// @notice HOOKLENS TEST FIXTURE. Requires a fresh, positive oracle answer before liquidity
///         can be removed. If the oracle reverts, reports zero or a negative value, or is
///         stale, every removal reverts: LP withdrawals depend on an external contract.
contract OracleGatedWithdrawalHook is FixtureBaseHook {
    error NotOwner();
    error StaleOraclePrice(uint256 updatedAt, uint256 nowTs, uint256 maxStaleness);
    error InvalidOraclePrice(int256 answer);

    event OracleUpdated(address oldOracle, address newOracle);
    event MaxStalenessUpdated(uint256 oldValue, uint256 newValue);

    address public owner;
    IAggregatorLike public oracle;
    uint256 public maxStaleness;

    constructor(IPoolManager _poolManager, address _owner, IAggregatorLike _oracle, uint256 _maxStaleness)
        FixtureBaseHook(_poolManager, true)
    {
        owner = _owner;
        oracle = _oracle;
        maxStaleness = _maxStaleness;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function getHookPermissions() public pure override returns (Hooks.Permissions memory p) {
        p.beforeRemoveLiquidity = true;
    }

    function setOracle(IAggregatorLike newOracle) external onlyOwner {
        emit OracleUpdated(address(oracle), address(newOracle));
        oracle = newOracle;
    }

    function setMaxStaleness(uint256 newValue) external onlyOwner {
        emit MaxStalenessUpdated(maxStaleness, newValue);
        maxStaleness = newValue;
    }

    function beforeRemoveLiquidity(address, PoolKey calldata, ModifyLiquidityParams calldata, bytes calldata)
        external
        view
        override
        onlyPoolManager
        returns (bytes4)
    {
        (, int256 answer,, uint256 updatedAt,) = oracle.latestRoundData();
        if (answer <= 0) revert InvalidOraclePrice(answer);
        if (block.timestamp > updatedAt && block.timestamp - updatedAt > maxStaleness) {
            revert StaleOraclePrice(updatedAt, block.timestamp, maxStaleness);
        }
        return this.beforeRemoveLiquidity.selector;
    }
}
