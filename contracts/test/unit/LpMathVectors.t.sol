// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Test} from "forge-std/Test.sol";
import {TickMath} from "@uniswap/v4-core/src/libraries/TickMath.sol";
import {SqrtPriceMath} from "@uniswap/v4-core/src/libraries/SqrtPriceMath.sol";
import {LiquidityAmounts} from "@uniswap/v4-core/test/utils/LiquidityAmounts.sol";

/// @notice Emits golden vectors from the Uniswap v4-core math libraries. The HookLens Python
///         LP engine (backend/app/lp/math.py) is tested against these exact integer outputs.
///   forge test --match-contract LpMathVectors
///   -> sim-out/vectors/lp_math.json (copied to backend/tests/fixtures/lp_math_vectors.json)
contract LpMathVectors is Test {
    string internal json;
    uint256 internal n;

    function _push(string memory obj) internal {
        json = n == 0 ? obj : string.concat(json, ",", obj);
        n++;
    }

    function test_emitVectors() public {
        int24[17] memory ticks = [
            TickMath.MIN_TICK,
            int24(-887220),
            int24(-500000),
            int24(-200340),
            int24(-200311),
            int24(-60),
            int24(-1),
            int24(0),
            int24(1),
            int24(60),
            int24(1000),
            int24(73136),
            int24(200340),
            int24(500000),
            int24(887220),
            int24(887271),
            TickMath.MAX_TICK
        ];
        for (uint256 i; i < ticks.length; i++) {
            uint160 sp = TickMath.getSqrtPriceAtTick(ticks[i]);
            // getTickAtSqrtPrice is defined on [MIN_SQRT_PRICE, MAX_SQRT_PRICE); MAX_TICK maps to the excluded bound.
            int24 back = sp < TickMath.MAX_SQRT_PRICE ? TickMath.getTickAtSqrtPrice(sp) : ticks[i];
            _push(
                string.concat(
                    "{\"kind\":\"tick\",\"tick\":",
                    vm.toString(int256(ticks[i])),
                    ",\"sqrt_price_x96\":\"",
                    vm.toString(uint256(sp)),
                    "\",\"tick_at_sqrt\":",
                    vm.toString(int256(back)),
                    "}"
                )
            );
            if (sp < TickMath.MAX_SQRT_PRICE - 1) {
                int24 nudged = TickMath.getTickAtSqrtPrice(sp + 1);
                _push(
                    string.concat(
                        "{\"kind\":\"sqrt\",\"sqrt_price_x96\":\"",
                        vm.toString(uint256(sp) + 1),
                        "\",\"tick\":",
                        vm.toString(int256(nudged)),
                        "}"
                    )
                );
            }
        }

        // Position vectors: (current, lower, upper, amount0, amount1) across below/in/above range.
        int24[3][6] memory ranges = [
            [int24(-200340), int24(-206340), int24(-194280)],
            [int24(-210000), int24(-206340), int24(-194280)],
            [int24(-190000), int24(-206340), int24(-194280)],
            [int24(0), int24(-600), int24(600)],
            [int24(10), int24(-887220), int24(887220)],
            [int24(-5), int24(-60), int24(60)]
        ];
        uint256[2][3] memory amounts = [[uint256(1e18), uint256(2000e6)], [uint256(5e15), uint256(1)], [uint256(123456789), uint256(987654321987)]];
        for (uint256 i; i < ranges.length; i++) {
            for (uint256 j; j < amounts.length; j++) {
                _positionVector(ranges[i][0], ranges[i][1], ranges[i][2], amounts[j][0], amounts[j][1]);
            }
        }
        vm.createDir("sim-out/vectors", true);
        vm.writeFile(
            "sim-out/vectors/lp_math.json",
            string.concat("{\"source\":\"uniswap/v4-core TickMath, SqrtPriceMath, LiquidityAmounts\",\"vectors\":[", json, "]}")
        );
    }

    function _positionVector(int24 tick, int24 tl, int24 tu, uint256 amt0, uint256 amt1) internal {
        uint160 sp = TickMath.getSqrtPriceAtTick(tick);
        uint160 sa = TickMath.getSqrtPriceAtTick(tl);
        uint160 sb = TickMath.getSqrtPriceAtTick(tu);
        uint128 liq = LiquidityAmounts.getLiquidityForAmounts(sp, sa, sb, amt0, amt1);
        (uint256 a0, uint256 a1) = LiquidityAmounts.getAmountsForLiquidity(sp, sa, sb, liq);
        (uint256 d0Up, uint256 d1Up) = _mintAmounts(sp, sa, sb, liq);
        string memory obj = string.concat(
            "{\"kind\":\"position\",\"tick\":",
            vm.toString(int256(tick)),
            ",\"tick_lower\":",
            vm.toString(int256(tl)),
            ",\"tick_upper\":",
            vm.toString(int256(tu)),
            ",\"amount0_in\":\"",
            vm.toString(amt0),
            "\",\"amount1_in\":\"",
            vm.toString(amt1)
        );
        obj = string.concat(
            obj,
            "\",\"liquidity\":\"",
            vm.toString(uint256(liq)),
            "\",\"amount0_for_liquidity\":\"",
            vm.toString(a0),
            "\",\"amount1_for_liquidity\":\"",
            vm.toString(a1),
            "\",\"amount0_mint_round_up\":\"",
            vm.toString(d0Up),
            "\",\"amount1_mint_round_up\":\"",
            vm.toString(d1Up),
            "\"}"
        );
        _push(obj);
    }

    /// @dev Amounts the PoolManager charges to mint `liq` (rounded up), per v4 Pool.modifyLiquidity.
    function _mintAmounts(uint160 sp, uint160 sa, uint160 sb, uint128 liq) internal pure returns (uint256 d0, uint256 d1) {
        if (sp < sa) {
            d0 = SqrtPriceMath.getAmount0Delta(sa, sb, liq, true);
        } else if (sp < sb) {
            d0 = SqrtPriceMath.getAmount0Delta(sp, sb, liq, true);
            d1 = SqrtPriceMath.getAmount1Delta(sa, sp, liq, true);
        } else {
            d1 = SqrtPriceMath.getAmount1Delta(sa, sb, liq, true);
        }
    }

    /// @dev Sanity: round-trip tick -> sqrt -> tick holds for all usable ticks (fuzzed).
    function testFuzz_tickRoundTrip(int24 tick) public pure {
        tick = int24(bound(tick, TickMath.MIN_TICK, TickMath.MAX_TICK));
        assertEq(TickMath.getTickAtSqrtPrice(TickMath.getSqrtPriceAtTick(tick)), tick);
    }
}
