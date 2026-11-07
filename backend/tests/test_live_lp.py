"""Live pool state, live LP exposure and position-aware withdrawal interpretation.

RPC responses are mocked here only, inside these isolated unit tests (httpx.MockTransport), to
exercise failure paths deterministically. Production code never uses mocked data; the Anvil
integration suite (`-m anvil`) exercises the same service against a real node.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.chains import ChainConfig
from app.db.base import session_scope
from app.errors import AppError
from app.services.live_pool import (
    LivePoolService,
    LiveStateUnavailable,
    compute_pool_id,
    set_live_pool_service,
    validate_pool_identity,
)
from app.services.pools import LIQUIDITY_OFFSET, pool_state_slot
from app.services.rpc import RpcClient
from app.simulation.catalog import SCENARIOS
from app.simulation.decode import Registry
from app.simulation.forge_runner import ForgeRun
from app.simulation.interpret import interpret, observed_findings
from app.simulation.positions import (
    EMPTY_POSITION_SELECTOR,
    annotate_steps,
    position_creation,
    removal_outcome,
    withdrawal_summary,
)
from hooklens.analyzers.core import Collector

PM = "0x000000000004444c5dc75cb358380d2e3de08a90"
HOOK = "0x0207bcb5fc4b740167c578e59bde59801e78e888"
C0 = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"  # 8 decimals (WBTC-like)
C1 = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"  # 18 decimals (WETH-like)
POOL_ID = compute_pool_id(C0, C1, 2500, 1, HOOK)
# sqrtPriceX96 for tick 265524 (about 33.96 token1 per token0 after decimals).
SQRT_LIVE = 46171693016484785217659839262446665
TICK_LIVE = 265524
SQRT_OLD = 43000000000000000000000000000000000
TICK_OLD = 264100


def _chain(rpc_url: str | None = "http://rpc.test", chain_id: int = 1) -> ChainConfig:
    return ChainConfig(
        chain_id=chain_id,
        name="Ethereum Mainnet",
        short_name="eth",
        native_symbol="ETH",
        pool_manager=PM,
        pool_manager_deploy_block=0,
        explorer_name=None,
        explorer_url=None,
        rpc_url=rpc_url,
    )


def _pool(state: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "pool_id": POOL_ID,
        "currency0": C0,
        "currency1": C1,
        "fee": 2500,
        "tick_spacing": 1,
        "hooks": HOOK,
        "token0": {"symbol": "WBTC", "decimals": 8},
        "token1": {"symbol": "WETH", "decimals": 18},
        "state": state
        or {
            "initialized": True,
            "sqrt_price_x96": str(SQRT_OLD),
            "tick": TICK_OLD,
            "liquidity": "999",
            "lp_fee": 2500,
            "protocol_fee": 0,
            "block_number": 50,
        },
    }


class FakeNode:
    """A minimal JSON-RPC node: latest block, chain id and PoolManager extsload."""

    def __init__(self) -> None:
        self.block = 1000
        self.chain_id = 1
        self.sqrt = SQRT_LIVE
        self.tick = TICK_LIVE
        self.liquidity = 0
        self.fail: str | None = None
        self.delay = 0.0
        self.calls: Counter[str] = Counter()
        self.call_blocks: list[str] = []
        self._lock = threading.Lock()

    def word0(self) -> int:
        return self.sqrt | ((self.tick & 0xFFFFFF) << 160) | (0 << 184) | (2500 << 208)

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        m = body["method"]
        with self._lock:
            self.calls[m] += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail == "http500":
            return httpx.Response(500)
        if self.fail == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if m == "eth_chainId":
            res: Any = hex(self.chain_id)
        elif m == "eth_getBlockByNumber":
            res = {
                "number": hex(self.block),
                "hash": "0x" + f"{self.block:064x}",
                "timestamp": hex(1_800_000_000 + self.block * 12),
            }
        elif m == "eth_call":
            call, blk = body["params"]
            assert call["to"].lower() == PM
            self.call_blocks.append(blk)
            slot = int(call["data"][10:], 16)
            base = pool_state_slot(POOL_ID)
            word = self.word0() if slot == base else self.liquidity if slot == base + LIQUIDITY_OFFSET else 0
            res = "0x" + f"{word:064x}"
        else:
            raise AssertionError(m)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": res})


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.rpc.time.sleep", lambda _s: None)


@pytest.fixture()
def node() -> FakeNode:
    return FakeNode()


def _service(node: FakeNode) -> LivePoolService:
    def factory(chain: ChainConfig) -> RpcClient:
        url = chain.rpc_url or "http://rpc.test"  # tests run with no real RPC configured
        return RpcClient(dataclasses.replace(chain, rpc_url=url), transport=httpx.MockTransport(node.handler))

    return LivePoolService(factory)


# ---------------------------------------------------------------- live service


def test_live_state_reads_the_latest_block_with_provenance(node: FakeNode) -> None:
    svc = _service(node)
    out = svc.pool_state(_chain(), _pool(), hook=HOOK)
    assert out["source"] == "live" and out["chain_id"] == 1 and out["pool_manager"] == PM
    assert out["block_number"] == 1000 and out["block_hash"] == "0x" + f"{1000:064x}"
    assert out["block_timestamp"] == 1_800_000_000 + 12000 and out["block_time"].startswith("2027-")
    assert out["fetched_at"] and out["head_fetched_at"]
    st = out["state"]
    assert st["sqrt_price_x96"] == str(SQRT_LIVE) and st["tick"] == TICK_LIVE and st["lp_fee"] == 2500
    assert st["liquidity"] == "0" and st["block_number"] == 1000
    # Both slots are read at the same block that was reported as the head (consistent snapshot).
    assert node.call_blocks == [hex(1000), hex(1000)]


def test_state_cache_is_keyed_by_block_and_never_serves_an_older_block(node: FakeNode) -> None:
    svc = _service(node)
    svc.pool_state(_chain(), _pool())
    svc.pool_state(_chain(), _pool())
    assert node.calls["eth_call"] == 2 and node.calls["eth_getBlockByNumber"] == 1  # head + state cached

    node.block, node.tick = 1001, TICK_LIVE + 5
    node.sqrt = SQRT_LIVE + 10**30
    out = svc.pool_state(_chain(), _pool(), force=True)  # refresh: new head -> new cache key
    assert out["block_number"] == 1001 and out["state"]["tick"] == TICK_LIVE + 5
    assert out["cache"]["state_hit"] is False and node.calls["eth_call"] == 4


def test_concurrent_requests_share_one_rpc_round_trip(node: FakeNode) -> None:
    node.delay = 0.05
    svc = _service(node)
    results: list[int] = []

    def go() -> None:
        results.append(svc.pool_state(_chain(), _pool())["block_number"])

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [1000] * 8
    assert node.calls["eth_getBlockByNumber"] == 1 and node.calls["eth_call"] == 2


@pytest.mark.parametrize("fail", ["http500", "timeout"])
def test_rpc_failures_raise_and_are_not_cached(node: FakeNode, fail: str) -> None:
    node.fail = fail
    svc = _service(node)
    with pytest.raises(LiveStateUnavailable) as e:
        svc.pool_state(_chain(), _pool())
    assert e.value.code == "live_state_unavailable" and e.value.status_code == 503
    assert e.value.details["cause"] == "rpc_unavailable" and e.value.retryable
    node.fail = None
    assert svc.pool_state(_chain(), _pool())["block_number"] == 1000  # recovers; no stale failure cached


def test_chain_id_mismatch_and_missing_rpc_are_reported(node: FakeNode) -> None:
    node.chain_id = 11155111
    with pytest.raises(LiveStateUnavailable) as e:
        _service(node).pool_state(_chain(), _pool())
    assert e.value.details["cause"] == "chain_id_mismatch"

    svc = LivePoolService(lambda chain: RpcClient(chain))  # chain without an RPC URL
    with pytest.raises(LiveStateUnavailable) as e2:
        svc.pool_state(_chain(rpc_url=None), _pool())
    assert e2.value.details["cause"] == "rpc_not_configured" and not e2.value.retryable


def test_invalid_pool_identity_and_uninitialized_pool(node: FakeNode) -> None:
    svc = _service(node)
    with pytest.raises(AppError) as e:
        svc.pool_state(_chain(), {**_pool(), "fee": 3000})  # key no longer hashes to the ID
    assert e.value.code == "pool_identity_mismatch"
    with pytest.raises(AppError) as e2:
        validate_pool_identity(_pool(), hook="0x" + "99" * 20)
    assert e2.value.code == "pool_hook_mismatch"
    with pytest.raises(AppError) as e3:
        validate_pool_identity({"pool_id": POOL_ID})
    assert e3.value.code == "pool_key_incomplete"

    node.sqrt = 0
    with pytest.raises(AppError) as e4:
        svc.pool_state(_chain(), _pool())
    assert e4.value.code == "pool_not_initialized" and e4.value.status_code == 404


def test_pool_id_matches_v4_pool_key_hash() -> None:
    # Known mainnet ETH/USDC v4 pool (fee 500, tickSpacing 10, no hook).
    pid = compute_pool_id(
        "0x0000000000000000000000000000000000000000",
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        500,
        10,
        "0x0000000000000000000000000000000000000000",
    )
    assert pid == "0x21c67e77068de97969ba93d4aab21826d33ca12bb9f565d8496e8fda8a82ca27"


# ---------------------------------------------------------------- withdrawal interpretation

WRAPPED_REJECT = (
    "0x90bfb865"  # WrappedError(address,bytes4,bytes,bytes): the hook reverted inside beforeAddLiquidity
    + "00" * 12
    + HOOK[2:]
    + "259982e5"
    + "00" * 28
)


def _s(
    name: str,
    obs: str,
    *,
    cond: str = "baseline",
    phase: str = "baseline",
    met: bool | None = None,
    revert_data: str = "0x",
    liq: int | None = None,
    exp: str = "success",
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "name": name,
        "phase": phase,
        "condition": cond,
        "lp_expectation": exp,
        "observed": obs,
        "expectation_met": (obs == "success") if met is None else met,
        "privileged": False,
        "revert_data": revert_data,
    }
    if liq is not None:
        step["metrics"] = {"position_liquidity_before": str(liq)}
    return step


def _rejected_then_empty() -> list[dict[str, Any]]:
    """Exactly the shape of the user's mainnet run: the hook rejects the deposit, every removal is empty."""
    empty = EMPTY_POSITION_SELECTOR
    return [
        _s("add_liquidity", "revert", revert_data=WRAPPED_REJECT),
        _s("trader_swap_0_for_1", "success", exp="observe"),
        _s("partial_remove_50pct", "revert", revert_data=empty),
        _s("full_remove", "revert", revert_data=empty),
        _s(
            "add_before_external_revert",
            "revert",
            cond="external_revert",
            phase="condition_setup",
            revert_data=WRAPPED_REJECT,
        ),
        _s("remove_under_external_revert", "revert", cond="external_revert", phase="adversarial", revert_data=empty),
        _s("recover_after_external_revert", "revert", cond="external_revert", phase="recovery", revert_data=empty),
    ]


class _Run:
    def __init__(self, scenario_id: str, status: str, steps: list[dict[str, Any]]) -> None:
        self.scenario_id, self.status, self.steps = scenario_id, status, steps


def test_add_rejected_then_empty_removals_are_not_tested() -> None:
    steps = _rejected_then_empty()
    assert position_creation(steps)["status"] == "rejected"
    outcomes = {s["name"]: removal_outcome(s) for s in steps if removal_outcome(s)}
    assert set(outcomes.values()) == {"not_tested_no_position"}
    w = withdrawal_summary({"withdrawal_failure": _Run("withdrawal_failure", "unexpected_revert", steps)})
    assert w["status"] == "not_tested" and w["position_creation"]["status"] == "rejected"
    ann = {s["name"]: s for s in annotate_steps(steps)}
    assert ann["remove_under_external_revert"]["step_status"] == "not_tested"
    assert ann["remove_under_external_revert"]["position_check"] == {
        "had_position": False,
        "basis": "PoolManager reverted with CannotUpdateEmptyPosition()",
    }
    assert "step_status" not in ann["add_liquidity"] or ann["add_liquidity"]["step_status"] != "not_tested"


def _write(tmp: Path, steps: list[dict[str, Any]]) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "withdrawal_failure.json").write_text(
        json.dumps({"scenario": "withdrawal_failure", "block_number": 7, "infra_error": "", "steps": steps})
    )


def test_interpretation_and_findings_never_claim_a_blocked_withdrawal_without_a_position(tmp_path: Path) -> None:
    _write(tmp_path, _rejected_then_empty())
    i = interpret(SCENARIOS["withdrawal_failure"], ForgeRun("completed", 0, 100, {}, ""), tmp_path, Registry(), {})
    st = {s["name"]: s["step_status"] for s in i.steps}
    assert st["add_liquidity"] == "unexpected_revert"
    assert {st[n] for n in ("partial_remove_50pct", "full_remove", "remove_under_external_revert")} == {"not_tested"}
    assert i.status == "unexpected_revert"
    assert i.reason.startswith("Position creation rejected at add_liquidity")
    assert "not tested because no position was created" in i.reason
    assert "remove_under_external_revert" not in i.reason.split("not met:")[1].split(";")[0]
    assert i.meta["position_creation"]["status"] == "rejected"

    col = Collector(scope=HOOK)
    observed_findings(col, "withdrawal_failure", i, simulation_id="s", repro="x")
    rules = {f.rule_id for f in col.findings.values()}
    assert not any(r.startswith("withdrawal_") for r in rules)
    assert rules == {"baseline_operation_failed_add_liquidity", "expectation_not_met_add_before_external_revert"}


def test_created_position_then_successful_removal_is_completed() -> None:
    steps = [
        _s("add_liquidity", "success"),
        _s("partial_remove_50pct", "success", liq=1000),
        _s("full_remove", "success", liq=500),
    ]
    w = withdrawal_summary({"withdrawal_failure": _Run("withdrawal_failure", "passed", steps)})
    assert w["status"] == "completed" and w["position_creation"]["status"] == "created"
    assert {o["outcome"] for o in w["outcomes"]} == {"completed"}


def test_created_position_then_genuine_withdrawal_failure_is_blocked(tmp_path: Path) -> None:
    oracle_revert = "0x" + "08c379a0" + "00" * 28  # Error(string) shaped; not an empty-position error
    steps = [
        _s("add_liquidity", "success"),
        _s("add_before_oracle_revert", "success", cond="oracle_revert", phase="condition_setup"),
        _s(
            "remove_under_oracle_revert",
            "revert",
            cond="oracle_revert",
            phase="adversarial",
            revert_data=oracle_revert,
            liq=12345,
            met=False,
        ),
    ]
    w = withdrawal_summary({"withdrawal_failure": _Run("withdrawal_failure", "unexpected_revert", steps)})
    assert w["status"] == "blocked"
    assert [o["outcome"] for o in w["outcomes"]] == ["blocked"]

    _write(tmp_path, steps)
    i = interpret(SCENARIOS["withdrawal_failure"], ForgeRun("completed", 0, 100, {}, ""), tmp_path, Registry(), {})
    col = Collector(scope=HOOK)
    observed_findings(col, "withdrawal_failure", i, simulation_id="s", repro="x")
    assert "withdrawal_blocked_oracle_revert" in {f.rule_id for f in col.findings.values()}


def test_recovery_after_a_cleared_condition_is_not_success_under_it() -> None:
    """`recover_after_X` runs once X is cleared; it must not read as 'removal succeeded under X'."""
    from fractions import Fraction
    from types import SimpleNamespace

    from app.lp.valuation import simulation_effects

    oracle_revert = "0x" + "08c379a0" + "00" * 28
    steps = [
        _s("add_liquidity", "success", liq=0),
        _s("remove_under_oracle_revert", "revert", cond="oracle_revert", revert_data=oracle_revert, liq=7, met=False),
        _s("recover_after_oracle_revert", "success", cond="oracle_revert", phase="recovery", liq=7),
        _s("full_remove", "success", cond="baseline", liq=7),
    ]
    sim = SimpleNamespace(
        id="s", status="completed", fork_block=10, spec={}, runs=[_Run("withdrawal_failure", "completed", steps)]
    )
    pos = SimpleNamespace(tick_lower=0, tick_upper=60, dec0=18, dec1=18)
    fx = simulation_effects(sim, pos, Fraction(1), state_block=12)  # type: ignore[arg-type]
    assert [b["condition"] for b in fx["withdrawal_blocked_under"]] == ["oracle_revert"]
    assert fx["withdrawal_recovered_after"] == ["oracle_revert"]
    assert "oracle_revert" not in fx["withdrawal_succeeded_under"]
    assert fx["withdrawal_succeeded_under"] == ["baseline"]


def test_harness_metric_zero_position_overrides_a_generic_revert() -> None:
    step = _s("remove_under_paused", "revert", cond="paused", phase="adversarial", revert_data="0xdeadbeef", liq=0)
    assert removal_outcome(step) == "not_tested_no_position"
    step_live = {**step, "metrics": {"position_liquidity_before": "77"}}
    assert removal_outcome(step_live) == "blocked"


def test_unsupported_error_and_incomplete_runs() -> None:
    assert withdrawal_summary({"withdrawal_failure": _Run("withdrawal_failure", "unsupported", [])})["status"] == (
        "unsupported"
    )
    assert withdrawal_summary({"oracle_failure": _Run("oracle_failure", "infra_error", [])})["status"] == (
        "execution_error"
    )
    only_add = [_s("add_liquidity", "success")]
    w = withdrawal_summary({"withdrawal_failure": _Run("withdrawal_failure", "partial", only_add)})
    assert w["status"] == "not_tested" and w["outcomes"] == []
    assert withdrawal_summary({})["status"] == "not_tested"


# ---------------------------------------------------------------- API


def _workspace(client: Any) -> tuple[str, dict[str, str]]:
    from app.api.security import verify_token

    token = client.get("/v1/scans").headers["X-HookLens-Workspace"]
    ws = verify_token(token)
    assert ws
    return ws, {"X-HookLens-Workspace": token}


def _seed(ws: str, *, with_sim: bool = False) -> tuple[str, str | None, str | None]:
    from app.db.models import Scan, ScenarioRun, Simulation

    with session_scope() as db:
        scan = Scan(
            workspace_id=ws, chain_id=1, hook_address=HOOK, status="completed", block_number=50, pools=[_pool()]
        )
        db.add(scan)
        db.flush()
        sim_id = run_id = None
        if with_sim:
            sim = Simulation(
                workspace_id=ws,
                scan_id=scan.id,
                status="completed",
                chain_id=1,
                pool_id=POOL_ID,
                fork_block=40,
                spec={"position": {"tick_lower": TICK_LIVE - 100, "tick_upper": TICK_LIVE + 100}},
            )
            db.add(sim)
            db.flush()
            run = ScenarioRun(
                simulation_id=sim.id,
                scenario_id="withdrawal_failure",
                status="unexpected_revert",
                steps=_rejected_then_empty(),
            )
            db.add(run)
            db.flush()
            sim_id, run_id = sim.id, run.id
        return scan.id, sim_id, run_id


@pytest.fixture()
def live_node() -> Any:
    n = FakeNode()
    set_live_pool_service(_service(n))
    yield n
    set_live_pool_service(None)


_BODY = {"price_lower": "30", "price_upper": "38", "amount0": "0.1", "amount1": "10"}


def test_compare_uses_fresh_live_state_with_freshness_metadata(client: Any, live_node: FakeNode) -> None:
    ws, hdr = _workspace(client)
    scan_id, _, _ = _seed(ws)
    r = client.post("/v1/positions/compare", json={"scan_id": scan_id, **_BODY}, headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    src = body["data_source"]
    assert src["source"] == "live" and src["block_number"] == 1000 and src["block_hash"] and src["fetched_at"]
    assert body["pool"]["block_number"] == 1000 and body["pool"]["state"]["tick"] == TICK_LIVE  # not the snapshot
    base = body["baseline"]
    assert base["price"]["tag"] == "live" and base["current_tick"]["value"] == TICK_LIVE
    assert base["price"]["value"].startswith("33.96")
    assert {base[k]["tag"] for k in ("deposit_amount0", "deposit_amount1", "value_in_token1", "range_state")} == {
        "hypothetical"
    }
    assert base["share_of_active_liquidity"]["tag"] == "hypothetical"
    assert base["fee_income"]["tag"] == "unavailable"
    assert body["position_kind"]["kind"] == "modelled" and body["scenario_assumptions"]
    assert {p["tag"] for p in body["price_scenarios"]} == {"hypothetical"}


def test_compare_reports_rpc_failure_and_never_falls_back(client: Any, live_node: FakeNode) -> None:
    ws, hdr = _workspace(client)
    scan_id, _, _ = _seed(ws)
    live_node.fail = "http500"
    r = client.post("/v1/positions/compare", json={"scan_id": scan_id, **_BODY}, headers=hdr)
    assert r.status_code == 503
    assert r.json()["code"] == "live_state_unavailable"
    assert "baseline" not in r.json()


def test_historical_snapshot_is_separate_and_labelled(client: Any, live_node: FakeNode) -> None:
    ws, hdr = _workspace(client)
    scan_id, _, _ = _seed(ws)
    r = client.post(
        "/v1/positions/compare",
        json={"scan_id": scan_id, "state_source": "scan", "price_lower": "25", "price_upper": "38", "amount0": "0.1"},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_source"]["source"] == "historical" and body["data_source"]["block_number"] == 50
    assert body["baseline"]["price"]["tag"] == "historical" and body["baseline"]["current_tick"]["value"] == TICK_OLD
    assert live_node.calls["eth_call"] == 0  # historical mode reads no chain state


def test_live_endpoint_and_simulation_separation(client: Any, live_node: FakeNode) -> None:
    ws, hdr = _workspace(client)
    scan_id, sim_id, run_id = _seed(ws, with_sim=True)

    live = client.get(f"/v1/scans/{scan_id}/pools/{POOL_ID}/live", headers=hdr).json()
    assert live["source"] == "live" and live["block_number"] == 1000 and live["scan_block_number"] == 50
    assert live["price"]["token1_per_token0"].startswith("33.96") and live["token0"]["symbol"] == "WBTC"
    bad = client.get(f"/v1/scans/{scan_id}/pools/0x{'ab' * 32}/live", headers=hdr)
    assert bad.status_code == 422 and bad.json()["code"] == "pool_not_found"

    body = client.post(
        "/v1/positions/compare", json={"scan_id": scan_id, "simulation_id": sim_id, **_BODY}, headers=hdr
    ).json()
    eff = body["simulation_effects"]
    assert eff["source"] == "historical_simulation" and eff["fork_block"] == 40 and eff["state_block"] == 1000
    assert eff["blocks_since_simulation"] == 960
    assert eff["withdrawal_blocked_under"] == [] and eff["withdrawal"]["status"] == "not_tested"
    assert {n["step"] for n in eff["withdrawal_not_tested"]} >= {"remove_under_external_revert", "full_remove"}
    assert eff["position_creation"]["status"] == "rejected"
    assert body["position_kind"]["deposit_rejected_in_simulation"] is True

    # Run detail: stored evidence untouched, reading is position-aware.
    run = client.get(f"/v1/simulations/{sim_id}/runs/{run_id}", headers=hdr).json()
    st = {s["name"]: s for s in run["steps"]}
    assert st["remove_under_external_revert"]["step_status"] == "not_tested"
    assert st["remove_under_external_revert"]["withdrawal_outcome"] == "not_tested_no_position"
    with session_scope() as db:
        from app.db.models import ScenarioRun

        stored = db.get(ScenarioRun, run_id)
        assert stored is not None and "step_status" not in stored.steps[2]
