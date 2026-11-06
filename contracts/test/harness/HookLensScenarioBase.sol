// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Test, Vm} from "forge-std/Test.sol";
import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";
import {IHooks} from "@uniswap/v4-core/src/interfaces/IHooks.sol";
import {IERC20Minimal} from "@uniswap/v4-core/src/interfaces/external/IERC20Minimal.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "@uniswap/v4-core/src/types/PoolId.sol";
import {Currency, CurrencyLibrary} from "@uniswap/v4-core/src/types/Currency.sol";
import {StateLibrary} from "@uniswap/v4-core/src/libraries/StateLibrary.sol";
import {TickMath} from "@uniswap/v4-core/src/libraries/TickMath.sol";
import {PoolModifyLiquidityTestNoChecks} from "@uniswap/v4-core/src/test/PoolModifyLiquidityTestNoChecks.sol";
import {PoolSwapTest} from "@uniswap/v4-core/src/test/PoolSwapTest.sol";
import {LPActor, TraderActor, UnprivilegedActor, OpResult} from "../../src/harness/Actors.sol";

/// @title HookLensScenarioBase
/// @notice Shared harness for HookLens adversarial scenarios.
///
/// Configuration is supplied either by environment variables (when the HookLens backend
/// runs `forge test --fork-url ... --fork-block-number ...`) or programmatically by a
/// derived test that deploys fixtures locally. Each scenario records every step with the
/// LP-relevant expectation and the observed outcome, then writes a JSON result file that
/// the backend parses. Tests do not fail on observed behaviour unless HL_STRICT=true, so the
/// evidence is always produced; strict mode turns LP expectations into assertions.
abstract contract HookLensScenarioBase is Test {
    using PoolIdLibrary for PoolKey;
    using StateLibrary for IPoolManager;

    string internal constant HARNESS_VERSION = "hooklens-harness/1.0.0";

    bytes32 internal constant SWAP_EVENT_SIG =
        keccak256("Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)");

    // ---------------------------------------------------------------- configuration
    IPoolManager internal manager;
    PoolKey internal key;
    address internal hookOwner; // optional: privileged account detected by static analysis
    string internal outDir;
    bool internal strict;
    bool internal configured;
    int24 internal tickLower;
    int24 internal tickUpper;
    uint256 internal liquidity;
    uint256 internal swapAmount; // token0 units
    uint256 internal swapAmount1; // token1 units (value-comparable to swapAmount)
    uint256 internal fundAmount;

    // ---------------------------------------------------------------- actors
    PoolModifyLiquidityTestNoChecks internal lpRouter;
    PoolSwapTest internal swapRouter;
    LPActor internal lp;
    LPActor internal lp2;
    TraderActor internal trader;
    TraderActor internal trader2;
    UnprivilegedActor internal outsider;

    // ---------------------------------------------------------------- results
    string internal scenarioId;
    string internal stepsPath;
    string internal infraError;
    uint160 internal initialSqrtPriceX96;
    int24 internal initialTick;

    struct Step {
        string name;
        string phase;
        string condition;
        string lpExpectation; // "success" | "revert" | "observe" | "conserved"
        bool privileged;
        string note;
    }

    // ================================================================ configuration

    function _loadEnvConfig() internal {
        address hook = vm.envOr("HL_HOOK", address(0));
        if (hook == address(0)) return;
        manager = IPoolManager(vm.envAddress("HL_POOL_MANAGER"));
        key = PoolKey({
            currency0: Currency.wrap(vm.envAddress("HL_CURRENCY0")),
            currency1: Currency.wrap(vm.envAddress("HL_CURRENCY1")),
            fee: uint24(vm.envUint("HL_FEE")),
            tickSpacing: int24(vm.envInt("HL_TICK_SPACING")),
            hooks: IHooks(hook)
        });
        hookOwner = vm.envOr("HL_OWNER", address(0));
        outDir = vm.envOr("HL_OUT", string("sim-out"));
        strict = vm.envOr("HL_STRICT", false);
        liquidity = vm.envOr("HL_LIQUIDITY", uint256(1e18));
        swapAmount = vm.envOr("HL_SWAP_AMOUNT", uint256(1e15));
        swapAmount1 = vm.envOr("HL_SWAP_AMOUNT1", swapAmount);
        fundAmount = vm.envOr("HL_FUND_AMOUNT", uint256(1e30));
        int256 lower = vm.envOr("HL_TICK_LOWER", int256(type(int24).min));
        int256 upper = vm.envOr("HL_TICK_UPPER", int256(type(int24).min));
        _setup(lower, upper);
    }

    function _configure(
        IPoolManager _manager,
        PoolKey memory _key,
        address _owner,
        uint256 _liquidity,
        uint256 _swapAmount,
        uint256 _swapAmount1
    ) internal {
        manager = _manager;
        key = _key;
        hookOwner = _owner;
        outDir = vm.envOr("HL_OUT", string("sim-out"));
        strict = false;
        liquidity = _liquidity;
        swapAmount = _swapAmount;
        swapAmount1 = _swapAmount1;
        fundAmount = 1e30;
        _setup(int256(type(int24).min), int256(type(int24).min));
    }

    function _setup(int256 lower, int256 upper) private {
        configured = true;
        (uint160 sqrtPriceX96, int24 tick,,) = manager.getSlot0(key.toId());
        if (sqrtPriceX96 == 0) {
            infraError = "pool_not_initialized";
            return;
        }
        initialSqrtPriceX96 = sqrtPriceX96;
        initialTick = tick;
        int24 ts = key.tickSpacing;
        if (lower == int256(type(int24).min) || upper == int256(type(int24).min)) {
            // Default range: 100 tick-spacings either side of the current tick, aligned and clamped.
            int24 width = ts * 100;
            tickLower = _alignDown(tick - width, ts);
            tickUpper = _alignDown(tick + width, ts) + ts;
        } else {
            tickLower = int24(lower);
            tickUpper = int24(upper);
        }
        int24 minUsable = _alignUp(TickMath.MIN_TICK, ts);
        int24 maxUsable = _alignDown(TickMath.MAX_TICK, ts);
        if (tickLower < minUsable) tickLower = minUsable;
        if (tickUpper > maxUsable) tickUpper = maxUsable;

        lpRouter = new PoolModifyLiquidityTestNoChecks(manager);
        swapRouter = new PoolSwapTest(manager);
        lp = new LPActor(lpRouter);
        lp2 = new LPActor(lpRouter);
        trader = new TraderActor(swapRouter);
        trader2 = new TraderActor(swapRouter);
        outsider = new UnprivilegedActor();
        vm.label(address(lp), "LPActor");
        vm.label(address(lp2), "LPActor2");
        vm.label(address(trader), "TraderActor");
        vm.label(address(trader2), "TraderActor2");
        vm.label(address(outsider), "UnprivilegedActor");
        vm.label(address(key.hooks), "Hook");
        vm.label(address(manager), "PoolManager");

        address[4] memory funded = [address(lp), address(lp2), address(trader), address(trader2)];
        for (uint256 i; i < funded.length; i++) {
            _fund(key.currency0, funded[i]);
            _fund(key.currency1, funded[i]);
        }
        lp.approve(key);
        lp2.approve(key);
        trader.approve(key);
        trader2.approve(key);
    }

    function _fund(Currency c, address to) internal {
        if (c.isAddressZero()) vm.deal(to, fundAmount);
        else deal(Currency.unwrap(c), to, fundAmount);
    }

    function _requireConfigured() internal {
        if (!configured) {
            // No HookLens configuration supplied: this scenario is not applicable to plain `forge test`.
            vm.skip(true);
        }
    }

    // ================================================================ operations

    function _add(LPActor a, uint256 liq) internal returns (OpResult memory) {
        return a.modify(key, tickLower, tickUpper, int256(liq));
    }

    function _remove(LPActor a, uint256 liq) internal returns (OpResult memory) {
        return a.modify(key, tickLower, tickUpper, -int256(liq));
    }

    function _positionLiquidity(LPActor a) internal view returns (uint128 liq) {
        (liq,,) = manager.getPositionInfo(key.toId(), address(lpRouter), tickLower, tickUpper, a.positionSalt());
    }

    /// @notice Input amount for a swap direction (token0 in when zeroForOne, else token1 in).
    function _in(bool zeroForOne) internal view returns (uint256) {
        return zeroForOne ? swapAmount : swapAmount1;
    }

    /// @notice Output amount for an exact-output swap (token1 out when zeroForOne, else token0).
    function _out(bool zeroForOne) internal view returns (uint256) {
        return zeroForOne ? swapAmount1 : swapAmount;
    }

    function _swapExactIn(TraderActor t, bool zeroForOne, uint256 amount) internal returns (OpResult memory) {
        return t.swap(key, zeroForOne, -int256(amount));
    }

    function _swapExactOut(TraderActor t, bool zeroForOne, uint256 amount) internal returns (OpResult memory) {
        return t.swap(key, zeroForOne, int256(amount));
    }

    /// @notice Executes a swap while recording logs and returns the LP fee applied, as emitted
    ///         by the PoolManager Swap event (hundredths of a bip). Returns type(uint256).max when
    ///         no Swap event was observed (e.g. the swap reverted).
    function _swapWithFee(TraderActor t, bool zeroForOne, int256 amountSpecified)
        internal
        returns (OpResult memory r, uint256 lpFee)
    {
        vm.recordLogs();
        r = t.swap(key, zeroForOne, amountSpecified);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        lpFee = type(uint256).max;
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].emitter == address(manager) && logs[i].topics.length > 0 && logs[i].topics[0] == SWAP_EVENT_SIG)
            {
                (,,,,, uint24 f) = abi.decode(logs[i].data, (int128, int128, uint160, uint128, int24, uint24));
                lpFee = f;
            }
        }
    }

    function _privilegedCall(address account, address target, bytes memory data)
        internal
        returns (bool ok, bytes memory ret)
    {
        vm.prank(account);
        (ok, ret) = target.call(data);
    }

    function _balanceOf(Currency c, address who) internal view returns (uint256) {
        if (c.isAddressZero()) return who.balance;
        return IERC20Minimal(Currency.unwrap(c)).balanceOf(who);
    }

    // ================================================================ recording
    //
    // Steps are appended to a JSONL file as they happen. Files are not part of EVM state, so
    // they survive vm.revertToState(), which the scenarios use to isolate cases.

    function _begin(string memory id) internal {
        scenarioId = id;
        vm.createDir(outDir, true);
        stepsPath = string.concat(outDir, "/", id, ".steps.jsonl");
        vm.writeFile(stepsPath, "");
    }

    function _record(Step memory s, OpResult memory r) internal {
        _recordRaw(s, r.ok, r.revertData, r.amount0, r.amount1, r.gasUsed, "");
    }

    function _recordWithMetrics(Step memory s, OpResult memory r, string memory metricsJson) internal {
        _recordRaw(s, r.ok, r.revertData, r.amount0, r.amount1, r.gasUsed, metricsJson);
    }

    /// @param metricsJson additional JSON members (without braces) nested under "metrics", or "".
    function _recordRaw(
        Step memory s,
        bool ok,
        bytes memory revertData,
        int256 amount0,
        int256 amount1,
        uint256 gasUsed,
        string memory metricsJson
    ) internal {
        bool expectationMet = _expectationMet(s.lpExpectation, ok);
        string memory obj = string.concat(
            "{\"name\":\"",
            s.name,
            "\",\"phase\":\"",
            s.phase,
            "\",\"condition\":\"",
            s.condition,
            "\",\"lp_expectation\":\"",
            s.lpExpectation,
            "\",\"observed\":\"",
            ok ? "success" : "revert",
            "\",\"expectation_met\":",
            expectationMet ? "true" : "false"
        );
        obj = string.concat(
            obj,
            ",\"privileged\":",
            s.privileged ? "true" : "false",
            ",\"revert_data\":\"",
            vm.toString(revertData),
            "\",\"amount0\":\"",
            vm.toString(amount0),
            "\",\"amount1\":\"",
            vm.toString(amount1),
            "\",\"gas_used\":",
            vm.toString(gasUsed),
            ",\"block_timestamp\":",
            vm.toString(vm.getBlockTimestamp())
        );
        obj = string.concat(obj, ",\"note\":\"", s.note, "\"");
        if (bytes(metricsJson).length > 0) obj = string.concat(obj, ",\"metrics\":{", metricsJson, "}");
        obj = string.concat(obj, "}");
        vm.writeLine(stepsPath, obj);
        if (!expectationMet) emit log_named_string("HookLens LP expectation not met", s.name);
    }

    function _expectationMet(string memory expectation, bool ok) internal pure returns (bool) {
        bytes32 e = keccak256(bytes(expectation));
        if (e == keccak256("success") || e == keccak256("conserved")) return ok;
        if (e == keccak256("revert")) return !ok;
        return true; // "observe"
    }

    function _readSteps() internal returns (string[] memory lines) {
        string[] memory buf = new string[](256);
        uint256 n;
        while (n < buf.length) {
            string memory line = vm.readLine(stepsPath);
            if (bytes(line).length == 0) break;
            buf[n++] = line;
        }
        vm.closeFile(stepsPath);
        lines = new string[](n);
        for (uint256 i; i < n; i++) {
            lines[i] = buf[i];
        }
    }

    /// @notice Last recorded outcome for a named step (used by local fixture tests).
    function _stepResult(string memory name) internal returns (bool found, bool ok) {
        string[] memory lines = _readSteps();
        for (uint256 i; i < lines.length; i++) {
            if (keccak256(bytes(vm.parseJsonString(lines[i], ".name"))) == keccak256(bytes(name))) {
                found = true;
                ok = keccak256(bytes(vm.parseJsonString(lines[i], ".observed"))) == keccak256("success");
            }
        }
    }

    function _finish() internal {
        string[] memory lines = _readSteps();
        uint256 violations;
        string memory steps;
        for (uint256 i; i < lines.length; i++) {
            if (!vm.parseJsonBool(lines[i], ".expectation_met")) violations++;
            steps = i == 0 ? lines[i] : string.concat(steps, ",", lines[i]);
        }
        string memory meta = string.concat(
            "{\"scenario\":\"",
            scenarioId,
            "\",\"harness_version\":\"",
            HARNESS_VERSION,
            "\",\"chain_id\":",
            vm.toString(block.chainid),
            ",\"block_number\":",
            vm.toString(block.number),
            ",\"pool_manager\":\"",
            vm.toString(address(manager)),
            "\",\"hook\":\"",
            vm.toString(address(key.hooks)),
            "\",\"pool_id\":\"",
            vm.toString(PoolId.unwrap(key.toId()))
        );
        meta = string.concat(
            meta,
            "\",\"currency0\":\"",
            vm.toString(Currency.unwrap(key.currency0)),
            "\",\"currency1\":\"",
            vm.toString(Currency.unwrap(key.currency1)),
            "\",\"fee\":",
            vm.toString(uint256(key.fee)),
            ",\"tick_spacing\":",
            vm.toString(int256(key.tickSpacing)),
            ",\"tick_lower\":",
            vm.toString(int256(tickLower)),
            ",\"tick_upper\":",
            vm.toString(int256(tickUpper))
        );
        meta = string.concat(
            meta,
            ",\"initial_sqrt_price_x96\":\"",
            vm.toString(uint256(initialSqrtPriceX96)),
            "\",\"initial_tick\":",
            vm.toString(int256(initialTick)),
            ",\"liquidity\":\"",
            vm.toString(liquidity),
            "\",\"swap_amount\":\"",
            vm.toString(swapAmount),
            "\",\"swap_amount1\":\"",
            vm.toString(swapAmount1),
            "\",\"violations\":",
            vm.toString(violations)
        );
        meta = string.concat(
            meta,
            ",\"infra_error\":\"",
            infraError,
            "\",\"actors\":{\"lp\":\"",
            vm.toString(address(lp)),
            "\",\"lp2\":\"",
            vm.toString(address(lp2)),
            "\",\"trader\":\"",
            vm.toString(address(trader)),
            "\",\"trader2\":\"",
            vm.toString(address(trader2)),
            "\",\"outsider\":\"",
            vm.toString(address(outsider)),
            "\",\"owner\":\"",
            vm.toString(hookOwner),
            "\"},\"steps\":[",
            steps,
            "]}"
        );
        vm.writeFile(string.concat(outDir, "/", scenarioId, ".json"), meta);
        if (strict) assertEq(violations, 0, "HookLens: LP expectations violated (see result JSON)");
    }

    /// @notice Returns true when setup failed (pool missing); records the infra error.
    function _abortIfInfraError() internal returns (bool) {
        if (bytes(infraError).length > 0) {
            _finish();
            return true;
        }
        return false;
    }

    // ================================================================ utils

    function _alignDown(int24 tick, int24 ts) internal pure returns (int24) {
        int24 c = tick / ts;
        if (tick < 0 && tick % ts != 0) c -= 1;
        return c * ts;
    }

    function _alignUp(int24 tick, int24 ts) internal pure returns (int24) {
        int24 d = _alignDown(tick, ts);
        return d == tick ? d : d + ts;
    }

    function _envBytesList(string memory name) internal view returns (bytes[] memory list) {
        string memory raw = vm.envOr(name, string(""));
        if (bytes(raw).length == 0) return new bytes[](0);
        return vm.envBytes(name, ",");
    }

    function _envStringList(string memory name) internal view returns (string[] memory list) {
        string memory raw = vm.envOr(name, string(""));
        if (bytes(raw).length == 0) return new string[](0);
        return vm.envString(name, ",");
    }

    function _metric(string memory k, int256 v) internal pure returns (string memory) {
        return string.concat("\"", k, "\":\"", vm.toString(v), "\"");
    }

    function _metricU(string memory k, uint256 v) internal pure returns (string memory) {
        return string.concat("\"", k, "\":\"", vm.toString(v), "\"");
    }
}
