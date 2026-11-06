// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {IHooks} from "@uniswap/v4-core/src/interfaces/IHooks.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {LPFeeLibrary} from "@uniswap/v4-core/src/libraries/LPFeeLibrary.sol";
import {TickMath} from "@uniswap/v4-core/src/libraries/TickMath.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {Currency} from "@uniswap/v4-core/src/types/Currency.sol";
import {ModifyLiquidityParams} from "@uniswap/v4-core/src/types/PoolOperation.sol";
import {PoolModifyLiquidityTestNoChecks} from "@uniswap/v4-core/src/test/PoolModifyLiquidityTestNoChecks.sol";
import {PoolSwapTest} from "@uniswap/v4-core/src/test/PoolSwapTest.sol";
import {MockERC20} from "solmate/src/test/utils/mocks/MockERC20.sol";
import {HookMiner} from "@uniswap/v4-periphery/test/shared/HookMiner.sol";

import {DynamicFeeHook} from "../fixtures/DynamicFeeHook.sol";
import {OracleGatedWithdrawalHook, IAggregatorLike} from "../fixtures/OracleGatedWithdrawalHook.sol";
import {PausableAdminHook} from "../fixtures/PausableAdminHook.sol";
import {HookProxy} from "../fixtures/HookProxy.sol";
import {SwapFeeDeltaHook} from "../fixtures/SwapFeeDeltaHook.sol";
import {NoOpHook} from "../fixtures/NoOpHook.sol";
import {MockOracle} from "../fixtures/MockOracle.sol";

/// @title FixtureDeployer
/// @notice Deploys the HookLens controlled fixture environment: two mock tokens with
///         different decimals, a mock oracle, five fixture hooks at mined addresses whose
///         low 14 bits encode their permissions, and one initialised, seeded pool per hook.
/// @dev `create2Deployer` is the address that executes `new X{salt: ...}`: the test contract
///      itself in `forge test`, or the canonical CREATE2 proxy in `forge script`.
abstract contract FixtureDeployer {
    address internal constant CREATE2_PROXY = 0x4e59b44847b379578588920cA78FbF26c0B4956C;
    int24 internal constant TICK_SPACING = 60;
    uint128 internal constant SEED_LIQUIDITY = 1e15;
    int24 internal constant SEED_HALF_WIDTH = 6000;

    struct Fixtures {
        IPoolManager manager;
        PoolModifyLiquidityTestNoChecks lpRouter;
        PoolSwapTest swapRouter;
        MockERC20 weth; // "HookLens Wrapped Ether" mock, 18 decimals
        MockERC20 usdc; // "HookLens USD" mock, 6 decimals
        MockOracle oracle;
        address dynamicFeeHook;
        address oracleGatedHook;
        address pausableHookProxy;
        address pausableHookImpl;
        address swapFeeDeltaHook;
        address noOpHook;
        PoolKey dynamicFeeKey;
        PoolKey oracleGatedKey;
        PoolKey pausableKey;
        PoolKey swapFeeDeltaKey;
        PoolKey noOpKey;
        int24 initialTick;
    }

    function _deployFixtures(IPoolManager manager, address owner, address create2Deployer)
        internal
        returns (Fixtures memory f)
    {
        f.manager = manager;
        f.lpRouter = new PoolModifyLiquidityTestNoChecks(manager);
        f.swapRouter = new PoolSwapTest(manager);
        f.weth = new MockERC20("HookLens Fixture WETH", "hlWETH", 18);
        f.usdc = new MockERC20("HookLens Fixture USD", "hlUSD", 6);
        f.oracle = new MockOracle(2000e8);

        // Price: 1 hlWETH = 2000 hlUSD. Raw price token1/token0 depends on sort order.
        bool wethIs0 = address(f.weth) < address(f.usdc);
        // log_1.0001(2000e6 / 1e18) ~= -200311; aligned to the tick spacing.
        f.initialTick = wethIs0 ? int24(-200340) : int24(200340);

        f.dynamicFeeHook = _mineAndDeploy(
            create2Deployer,
            uint160(Hooks.BEFORE_INITIALIZE_FLAG | Hooks.BEFORE_SWAP_FLAG),
            type(DynamicFeeHook).creationCode,
            abi.encode(manager, owner, uint24(3000), uint24(100), uint24(10000))
        );
        f.oracleGatedHook = _mineAndDeploy(
            create2Deployer,
            uint160(Hooks.BEFORE_REMOVE_LIQUIDITY_FLAG),
            type(OracleGatedWithdrawalHook).creationCode,
            abi.encode(manager, owner, IAggregatorLike(address(f.oracle)), uint256(1 hours))
        );
        f.pausableHookImpl = address(new PausableAdminHook(manager));
        f.pausableHookProxy = _mineAndDeploy(
            create2Deployer,
            uint160(Hooks.BEFORE_ADD_LIQUIDITY_FLAG | Hooks.BEFORE_REMOVE_LIQUIDITY_FLAG | Hooks.BEFORE_SWAP_FLAG),
            type(HookProxy).creationCode,
            abi.encode(f.pausableHookImpl, owner, abi.encodeCall(PausableAdminHook.initialize, (owner)))
        );
        f.swapFeeDeltaHook = _mineAndDeploy(
            create2Deployer,
            uint160(Hooks.AFTER_SWAP_FLAG | Hooks.AFTER_SWAP_RETURNS_DELTA_FLAG),
            type(SwapFeeDeltaHook).creationCode,
            abi.encode(manager, owner, uint256(30))
        );
        f.noOpHook = _mineAndDeploy(
            create2Deployer,
            uint160(Hooks.BEFORE_SWAP_FLAG | Hooks.AFTER_SWAP_FLAG),
            type(NoOpHook).creationCode,
            abi.encode(manager)
        );

        f.dynamicFeeKey = _key(f, f.dynamicFeeHook, LPFeeLibrary.DYNAMIC_FEE_FLAG);
        f.oracleGatedKey = _key(f, f.oracleGatedHook, 3000);
        f.pausableKey = _key(f, f.pausableHookProxy, 3000);
        f.swapFeeDeltaKey = _key(f, f.swapFeeDeltaHook, 3000);
        f.noOpKey = _key(f, f.noOpHook, 500);
    }

    /// @notice Initialise every fixture pool and seed it with liquidity from `funder`.
    ///         The caller must be `funder` (script broadcaster or test contract).
    function _seedPools(Fixtures memory f, address funder) internal {
        f.weth.mint(funder, 1e30);
        f.usdc.mint(funder, 1e30);
        f.weth.approve(address(f.lpRouter), type(uint256).max);
        f.usdc.approve(address(f.lpRouter), type(uint256).max);
        f.weth.approve(address(f.swapRouter), type(uint256).max);
        f.usdc.approve(address(f.swapRouter), type(uint256).max);
        PoolKey[5] memory keys = [f.dynamicFeeKey, f.oracleGatedKey, f.pausableKey, f.swapFeeDeltaKey, f.noOpKey];
        uint160 sqrtPrice = TickMath.getSqrtPriceAtTick(f.initialTick);
        for (uint256 i; i < keys.length; i++) {
            f.manager.initialize(keys[i], sqrtPrice);
            f.lpRouter.modifyLiquidity(
                keys[i],
                ModifyLiquidityParams({
                    tickLower: f.initialTick - SEED_HALF_WIDTH,
                    tickUpper: f.initialTick + SEED_HALF_WIDTH,
                    liquidityDelta: int256(uint256(SEED_LIQUIDITY)),
                    salt: bytes32(0)
                }),
                ""
            );
        }
    }

    function _key(Fixtures memory f, address hook, uint24 fee) internal pure returns (PoolKey memory k) {
        (address a, address b) = address(f.weth) < address(f.usdc)
            ? (address(f.weth), address(f.usdc))
            : (address(f.usdc), address(f.weth));
        k = PoolKey({
            currency0: Currency.wrap(a),
            currency1: Currency.wrap(b),
            fee: fee,
            tickSpacing: TICK_SPACING,
            hooks: IHooks(hook)
        });
    }

    function _mineAndDeploy(address deployer, uint160 flags, bytes memory creationCode, bytes memory args)
        internal
        returns (address deployed)
    {
        (address expected, bytes32 salt) = HookMiner.find(deployer, flags, creationCode, args);
        bytes memory init = abi.encodePacked(creationCode, args);
        if (deployer != CREATE2_PROXY) {
            assembly {
                deployed := create2(0, add(init, 32), mload(init), salt)
            }
        } else {
            // In scripts, deploy through the canonical CREATE2 proxy so the mined address holds.
            (bool ok,) = deployer.call(abi.encodePacked(salt, init));
            require(ok, "FixtureDeployer: CREATE2 proxy deployment failed");
            deployed = expected;
        }
        require(deployed == expected, "FixtureDeployer: mined address mismatch");
        require(deployed.code.length > 0, "FixtureDeployer: deployment failed");
    }
}
