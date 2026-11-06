// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @title MockOracle
/// @notice HOOKLENS TEST FIXTURE. Chainlink-style aggregator whose answer and timestamp
///         are fully controlled by its owner. Used to exercise oracle-dependent hooks.
contract MockOracle {
    error NotOwner();
    error OracleUnavailable();

    address public owner;
    int256 public answer;
    uint256 public updatedAt;
    uint80 public roundId;
    bool public unavailable;
    uint8 public constant decimals = 8;

    event AnswerUpdated(int256 indexed current, uint256 indexed roundId, uint256 updatedAt);

    constructor(int256 initialAnswer) {
        owner = msg.sender;
        _set(initialAnswer, block.timestamp);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function setAnswer(int256 newAnswer) external onlyOwner {
        _set(newAnswer, block.timestamp);
    }

    function setAnswerWithTimestamp(int256 newAnswer, uint256 timestamp) external onlyOwner {
        _set(newAnswer, timestamp);
    }

    function setUnavailable(bool value) external onlyOwner {
        unavailable = value;
    }

    function latestRoundData()
        external
        view
        returns (uint80 roundId_, int256 answer_, uint256 startedAt_, uint256 updatedAt_, uint80 answeredInRound_)
    {
        if (unavailable) revert OracleUnavailable();
        return (roundId, answer, updatedAt, updatedAt, roundId);
    }

    function _set(int256 newAnswer, uint256 timestamp) internal {
        answer = newAnswer;
        updatedAt = timestamp;
        roundId += 1;
        emit AnswerUpdated(newAnswer, roundId, timestamp);
    }
}
