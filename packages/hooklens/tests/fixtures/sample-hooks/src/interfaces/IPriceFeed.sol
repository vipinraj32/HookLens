// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice HOOKLENS CLI TEST FIXTURE: Chainlink-style feed interface.
interface IPriceFeed {
    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80);
}
