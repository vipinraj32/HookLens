// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Script, console2} from "forge-std/Script.sol";
import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {PoolManager} from "@uniswap/v4-core/src/PoolManager.sol";
import {PoolId, PoolIdLibrary} from "@uniswap/v4-core/src/types/PoolId.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {Currency} from "@uniswap/v4-core/src/types/Currency.sol";
import {FixtureDeployer} from "../src/harness/FixtureDeployer.sol";

/// @notice Deploys the HookLens fixture environment to a LOCAL development chain (Anvil).
///   anvil --code-size-limit 40000
///   forge script script/DeployFixtures.s.sol --rpc-url http://127.0.0.1:8545 --broadcast \
///     HL_DEPLOYER_KEY (defaults to the public Anvil dev key) <anvil dev key>
/// Writes deployments/<chainid>.json, consumed by the HookLens backend.
contract DeployFixtures is Script, FixtureDeployer {
    using PoolIdLibrary for PoolKey;

    function run() external {
        require(block.chainid == 31337, "DeployFixtures: local Anvil (31337) only");
        // Anvil's first well-known development key (public; local chain only).
        uint256 pk = vm.envOr(
            "HL_DEPLOYER_KEY", uint256(0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80)
        );
        address deployer = vm.addr(pk);
        vm.startBroadcast(pk);
        IPoolManager manager = IPoolManager(address(new PoolManager(deployer)));
        Fixtures memory f = _deployFixtures(manager, deployer, CREATE2_PROXY);
        _seedPools(f, deployer);
        vm.stopBroadcast();
        _write(f, deployer);
    }

    function _write(Fixtures memory f, address deployer) internal {
        string memory o = "deployment";
        vm.serializeUint(o, "chain_id", block.chainid);
        vm.serializeUint(o, "block_number", block.number);
        vm.serializeAddress(o, "deployer", deployer);
        vm.serializeAddress(o, "pool_manager", address(f.manager));
        vm.serializeAddress(o, "lp_router", address(f.lpRouter));
        vm.serializeAddress(o, "swap_router", address(f.swapRouter));
        vm.serializeAddress(o, "token_weth", address(f.weth));
        vm.serializeAddress(o, "token_usd", address(f.usdc));
        vm.serializeAddress(o, "oracle", address(f.oracle));
        vm.serializeInt(o, "initial_tick", f.initialTick);
        vm.serializeString(o, "hook_dynamic_fee", _hookJson("dynamic_fee", f.dynamicFeeHook, f.dynamicFeeKey));
        vm.serializeString(o, "hook_oracle_gated", _hookJson("oracle_gated", f.oracleGatedHook, f.oracleGatedKey));
        vm.serializeString(o, "hook_pausable_proxy", _hookJson("pausable_proxy", f.pausableHookProxy, f.pausableKey));
        vm.serializeAddress(o, "pausable_implementation", f.pausableHookImpl);
        vm.serializeString(o, "hook_swap_fee_delta", _hookJson("swap_fee_delta", f.swapFeeDeltaHook, f.swapFeeDeltaKey));
        string memory json = vm.serializeString(o, "hook_noop", _hookJson("noop", f.noOpHook, f.noOpKey));
        string memory path = string.concat(vm.projectRoot(), "/deployments/", vm.toString(block.chainid), ".json");
        vm.writeJson(json, path);
        console2.log("HookLens fixtures written to", path);
    }

    function _hookJson(string memory name, address hook, PoolKey memory k) internal returns (string memory) {
        string memory o = name;
        vm.serializeAddress(o, "address", hook);
        vm.serializeBytes32(o, "pool_id", PoolId.unwrap(k.toId()));
        vm.serializeAddress(o, "currency0", Currency.unwrap(k.currency0));
        vm.serializeAddress(o, "currency1", Currency.unwrap(k.currency1));
        vm.serializeUint(o, "fee", k.fee);
        return vm.serializeInt(o, "tick_spacing", k.tickSpacing);
    }
}
