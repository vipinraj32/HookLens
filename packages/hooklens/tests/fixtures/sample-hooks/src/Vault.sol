// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice HOOKLENS CLI TEST FIXTURE (non-hook contract): an owner-controlled ETH vault. It has admin
///         powers but nothing to do with Uniswap v4, so HookLens must not analyse it as a hook.
contract Vault {
    address public owner = msg.sender;

    receive() external payable {}

    function withdraw(uint256 amount) external {
        require(msg.sender == owner, "not owner");
        payable(owner).transfer(amount);
    }
}
