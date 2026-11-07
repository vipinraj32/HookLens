"""Builds a reproducible SimulationSpec from a completed scan.

Everything the Foundry harness receives is derived from the scan's deterministic outputs:
pool key and state (RPC), permissions (address bits), detected owner / oracle / pause / fee
setters / upgrade entry points (analyzers), and position sizes (exact LP math). Scenarios whose
preconditions are absent are marked `unsupported` with the reason, never silently skipped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eth_abi import encode as abi_encode

from app.config import get_settings
from app.errors import AppError
from app.lp import math as lpm
from app.services.evm import selector
from app.simulation.catalog import DEFAULT_ORDER, SCENARIOS
from hooklens.analyzers.rules.common import encode_probe_args

SPEC_VERSION = "hooklens-sim-spec/1.0.0"
HARNESS_FILES = (
    "test/harness/HookLensScenarioBase.sol",
    "test/harness/Scenarios.sol",
    "test/scenarios/HookLensScenarios.t.sol",
    "src/harness/Actors.sol",
)
DEFAULT_WHOLE_TOKENS = 10
RANGE_SPACINGS = 100  # matches the harness default range (100 tick spacings either side)


@dataclass
class ScenarioPlan:
    scenario_id: str
    applicable: bool
    reason: str
    env: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "applicable": self.applicable,
            "reason": self.reason,
            "env": self.env,
            "parameters": self.parameters,
            "notes": self.notes,
        }


@dataclass
class SimulationSpec:
    data: dict[str, Any]
    scenarios: list[ScenarioPlan]

    def to_dict(self) -> dict[str, Any]:
        return {**self.data, "scenarios": [s.to_dict() for s in self.scenarios]}


def harness_digest(contracts_dir: Path | None = None) -> str:
    root = contracts_dir or get_settings().contracts_dir
    h = hashlib.sha256()
    for rel in HARNESS_FILES:
        p = root / rel
        h.update(rel.encode())
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    return "sha256:" + h.hexdigest()


def _calldata(signature: str, types: list[str], values: list[Any]) -> str:
    return selector(signature) + abi_encode(types, values).hex()


def select_pool(pools: list[dict[str, Any]], pool_id: str | None) -> dict[str, Any]:
    if pool_id:
        for p in pools:
            if p["pool_id"].lower() == pool_id.lower():
                return p
        raise AppError("pool_not_found", f"Pool {pool_id} was not found among this scan's pools.", status_code=422)
    initialized = [p for p in pools if (p.get("state") or {}).get("initialized")]
    if not initialized:
        raise AppError(
            "no_pool",
            "No initialized pool uses this hook, so there is no pool to simulate against. "
            "Provide a pool ID that uses the hook, or initialize a pool on a local fork.",
            status_code=422,
        )
    # Prefer the pool with the most active liquidity: the most representative for LPs.
    return max(initialized, key=lambda p: int((p.get("state") or {}).get("liquidity") or 0))


def plan_position(pool: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    st = pool.get("state") or {}
    sqrt_price = int(st["sqrt_price_x96"])
    tick = int(st["tick"])
    ts = int(pool["tick_spacing"])
    min_usable, max_usable = lpm.usable_tick_bounds(ts)
    lower = options.get("tick_lower")
    upper = options.get("tick_upper")
    derivation: list[str] = []
    if lower is None or upper is None:
        width = ts * RANGE_SPACINGS
        lower = lpm.align_tick(tick - width, ts)
        upper = lpm.align_tick(tick + width, ts) + ts
        derivation.append(f"range = current tick {tick} ± {RANGE_SPACINGS} tick spacings ({ts}), aligned")
    lower, upper = int(lower), int(upper)
    if lower % ts or upper % ts:
        raise AppError("invalid_ticks", f"Ticks must be multiples of the tick spacing {ts}.", status_code=422)
    lower, upper = max(lower, min_usable), min(upper, max_usable)
    if lower >= upper:
        raise AppError("invalid_ticks", "tick_lower must be below tick_upper.", status_code=422)

    dec0 = (pool.get("token0") or {}).get("decimals")
    dec1 = (pool.get("token1") or {}).get("decimals")
    if dec0 is None or dec1 is None:
        derivation.append("token decimals unavailable: 18 assumed for sizing only")
    d0, d1 = (dec0 if dec0 is not None else 18), (dec1 if dec1 is not None else 18)
    amount0 = int(options.get("amount0") or DEFAULT_WHOLE_TOKENS * 10**d0)
    amount1 = int(options.get("amount1") or DEFAULT_WHOLE_TOKENS * 10**d1)
    sa, sb = lpm.get_sqrt_price_at_tick(lower), lpm.get_sqrt_price_at_tick(upper)
    liquidity = int(options.get("liquidity") or lpm.get_liquidity_for_amounts(sqrt_price, sa, sb, amount0, amount1))
    if liquidity <= 0:
        raise AppError(
            "position_too_small", "The requested amounts produce zero liquidity in this range.", status_code=422
        )
    mint0, mint1 = lpm.mint_amounts(sqrt_price, sa, sb, liquidity)
    derivation.append(
        f"liquidity = LiquidityAmounts.getLiquidityForAmounts(sqrtP, range, {amount0}, {amount1}) = {liquidity}"
        if not options.get("liquidity")
        else f"liquidity = {liquidity} (user supplied)"
    )
    swap0 = int(options.get("swap_amount0") or max(1, (mint0 // 10) if mint0 else 10**d0 // 100))
    swap1 = int(options.get("swap_amount1") or max(1, (mint1 // 10) if mint1 else 10**d1 // 100))
    derivation.append("swap sizes = 10% of the position's token amounts (exact input)")
    return {
        "tick_lower": lower,
        "tick_upper": upper,
        "current_tick": tick,
        "sqrt_price_x96": str(sqrt_price),
        "liquidity": str(liquidity),
        "amount0_target": str(amount0),
        "amount1_target": str(amount1),
        "mint_amount0": str(mint0),
        "mint_amount1": str(mint1),
        "swap_amount0": str(swap0),
        "swap_amount1": str(swap1),
        "range_state": "in-range" if lower <= tick < upper else ("below" if tick < lower else "above"),
        "decimals0": dec0,
        "decimals1": dec1,
        "derivation": derivation,
    }


def build_spec(scan: Any, contract: Any, options: dict[str, Any], *, run_dir_rel: str) -> SimulationSpec:
    facts: dict[str, Any] = dict((scan.analysis or {}).get("facts") or {})
    perms = scan.permissions or {}
    enabled = set(perms.get("enabled_flags") or [])
    pool = select_pool(list(scan.pools or []), options.get("pool_id"))
    position = plan_position(pool, options)

    base_env = {
        "HL_HOOK": scan.hook_address,
        "HL_POOL_MANAGER": _pool_manager(scan),
        "HL_CURRENCY0": pool["currency0"],
        "HL_CURRENCY1": pool["currency1"],
        "HL_FEE": str(pool["fee"]),
        "HL_TICK_SPACING": str(pool["tick_spacing"]),
        "HL_LIQUIDITY": position["liquidity"],
        "HL_SWAP_AMOUNT": position["swap_amount0"],
        "HL_SWAP_AMOUNT1": position["swap_amount1"],
        "HL_TICK_LOWER": str(position["tick_lower"]),
        "HL_TICK_UPPER": str(position["tick_upper"]),
        "HL_STRICT": "false",
    }
    owner = facts.get("owner")
    if owner:
        base_env["HL_OWNER"] = owner

    requested = options.get("scenarios") or list(DEFAULT_ORDER)
    unknown = [s for s in requested if s not in SCENARIOS]
    if unknown:
        raise AppError("unknown_scenario", f"Unknown scenarios: {unknown}. Known: {list(SCENARIOS)}", status_code=422)

    plans: list[ScenarioPlan] = []
    for sid in [s for s in DEFAULT_ORDER if s in requested]:
        p = _plan_scenario(sid, facts, enabled, pool, base_env)
        p.env = {**base_env, **p.env, "HL_OUT": f"{run_dir_rel}/{sid}"} if p.applicable else {}
        plans.append(p)

    data = {
        "spec_version": SPEC_VERSION,
        "chain_id": scan.chain_id,
        "fork_block": scan.block_number,
        "fork_block_hash": getattr(contract, "block_hash", None),
        "hook": scan.hook_address,
        "runtime_code_hash": getattr(contract, "runtime_code_hash", None),
        "is_proxy": getattr(contract, "is_proxy", False),
        "implementation": getattr(contract, "implementation_address", None),
        "implementation_code_hash": getattr(contract, "implementation_code_hash", None),
        "pool": {k: pool.get(k) for k in ("pool_id", "currency0", "currency1", "fee", "dynamic_fee", "tick_spacing")}
        | {"state": pool.get("state"), "token0": pool.get("token0"), "token1": pool.get("token1")},
        "position": position,
        "privileged_actor": {
            "owner": owner,
            "source": "analyzer fact (owner variable read at the pinned block)" if owner else None,
            "method": "vm.prank inside the fork only; no keys are used or required",
        },
        "harness": {"version": "hooklens-harness/1.1.0", "digest": harness_digest()},
        "determinism": "The harness uses no randomness; identical spec + fork block reproduce identical results.",
        "facts_used": sorted(
            k
            for k in facts
            if k
            in (
                "owner",
                "oracle",
                "pause_call",
                "external_targets",
                "fee_probes",
                "admin_calls",
                "upgrade_selector",
                "proxy_admin",
            )
        ),
    }
    return SimulationSpec(data=data, scenarios=plans)


def _pool_manager(scan: Any) -> str:
    from app.chains import get_chain

    pm = get_chain(scan.chain_id).pool_manager
    if not pm:
        raise AppError("pool_manager_unavailable", "No PoolManager is configured for this chain.", status_code=503)
    return pm


def _plan_scenario(
    sid: str, facts: dict[str, Any], enabled: set[str], pool: dict[str, Any], base_env: dict[str, str]
) -> ScenarioPlan:
    oracle = facts.get("oracle")
    if sid == "fee_escalation":
        probes = facts.get("fee_probes") or []
        can_alter = "BEFORE_SWAP" in enabled or bool(pool.get("dynamic_fee"))
        if not can_alter and not probes:
            return ScenarioPlan(
                sid,
                False,
                "The hook has no beforeSwap permission and the pool fee is static, so "
                "the hook cannot change the LP fee.",
            )
        calls, labels = [], []
        for pr in probes:
            calls.append(_calldata(pr["signature"], ["uint24"], [int(pr["value"])]))
            labels.append(pr["label"])
        env = {"HL_FEE_CALLS": ",".join(calls), "HL_FEE_LABELS": ",".join(labels)} if calls else {}
        notes = [] if calls else ["No fee setter was detected; only the effective baseline fee is measured."]
        return ScenarioPlan(
            sid, True, "beforeSwap / dynamic-fee capability present", env, {"fee_probes": probes}, notes
        )

    if sid == "withdrawal_failure":
        conditions: list[str] = []
        env = {}
        notes = []
        if oracle:
            env |= _oracle_env(oracle, notes)
            conditions += ["oracle_revert", "oracle_zero"]
            if oracle.get("kind") == "chainlink":
                conditions.append("oracle_negative")
            if oracle.get("staleness"):
                conditions.append("oracle_stale")
        if facts.get("pause_call") and facts.get("owner"):
            conditions.append("paused")
            env["HL_PAUSE_CALL"] = facts["pause_call"]
        ext = [t for t in (facts.get("external_targets") or []) if not oracle or t.lower() != oracle["address"].lower()]
        if ext:
            conditions.append("external_revert")
            env["HL_EXTERNAL_TARGETS"] = ",".join(ext)
        if conditions:
            env["HL_CONDITIONS"] = ",".join(conditions)
        else:
            notes.append("No withdrawal dependency was detected; only baseline add/remove/repeat is executed.")
        return ScenarioPlan(
            sid, True, "Always applicable: every LP needs to withdraw", env, {"conditions": conditions}, notes
        )

    if sid == "oracle_failure":
        if not oracle:
            return ScenarioPlan(sid, False, "No oracle dependency was detected in the hook callbacks.")
        notes = []
        env = _oracle_env(oracle, notes)
        return ScenarioPlan(
            sid,
            True,
            f"Oracle {oracle['address']} used by {', '.join(oracle.get('callbacks', []))}",
            env,
            {"oracle": oracle},
            notes,
        )

    if sid == "admin_upgrade":
        calls, labels, skipped = [], [], []
        for c in facts.get("admin_calls") or []:
            enc = encode_probe_args([("", t) for t in c.get("types", [])])
            if enc is None:
                skipped.append(c["signature"])
                continue
            calls.append(_calldata(c["signature"], *enc))
            labels.append(c["label"])
        upgrade = facts.get("upgrade_selector")
        if not calls and not upgrade:
            return ScenarioPlan(sid, False, "No privileged function or upgrade entry point was detected.")
        env = {}
        if calls:
            env["HL_ADMIN_CALLS"] = ",".join(calls)
            env["HL_ADMIN_LABELS"] = ",".join(labels)
        if upgrade:
            env["HL_UPGRADE_SELECTOR"] = str(int(upgrade, 16))
            if facts.get("proxy_admin"):
                env["HL_PROXY_ADMIN"] = facts["proxy_admin"]
        notes = [f"Not called (argument types not supported for probing): {', '.join(skipped)}"] if skipped else []
        if not facts.get("owner"):
            notes.append("No owner was detected, so only unauthorized calls are executed.")
        return ScenarioPlan(
            sid,
            True,
            "Privileged entry points detected",
            env,
            {"admin_calls": labels, "upgrade_selector": upgrade},
            notes,
        )

    if sid in ("accounting_invariants", "transaction_ordering"):
        return ScenarioPlan(sid, True, "Always applicable")
    raise AppError("unknown_scenario", sid, status_code=422)


def _oracle_env(oracle: dict[str, Any], notes: list[str]) -> dict[str, str]:
    env = {
        "HL_ORACLE": oracle["address"],
        "HL_ORACLE_SELECTOR": str(int(oracle["selector"], 16)),
        "HL_ORACLE_KIND": "chainlink" if oracle.get("kind") == "chainlink" else "uint",
    }
    st = oracle.get("staleness") or {}
    if st.get("seconds") is not None:
        # The harness advances time by exactly this many seconds; one past the threshold is stale.
        env["HL_STALE_SECONDS"] = str(int(st["seconds"]) + 1)
        notes.append(
            f"Staleness window {st['seconds']}s read from `{st.get('variable')}`; time is advanced by "
            f"{int(st['seconds']) + 1}s."
        )
    else:
        notes.append("No staleness threshold was read; the harness default (7 days) is used.")
    return env
