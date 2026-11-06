"""`hooklens lab` against a mocked HookLens API: real request flow, no invented results."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hooklens import lab
from hooklens.errors import AnalysisError, ConfigError, SourceError

HOOK = "0x0000000000000000000000000000000000000080"
POOL = "0x" + "11" * 32


def api(*, forge: bool = True, rpc: bool = True, runs: list[dict[str, Any]] | None = None) -> httpx.MockTransport:
    calls: list[str] = []
    runs = runs or [
        {
            "id": "r1",
            "scenario_id": "withdrawal_failure",
            "status": "passed",
            "status_reason": "ok",
            "repro_command": "forge test",
        },
        {"id": "r2", "scenario_id": "oracle_failure", "status": "unsupported", "status_reason": "no oracle detected"},
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        p, m = req.url.path, req.method
        calls.append(f"{m} {p}")
        if p == "/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if p == "/v1/health/worker":
            return httpx.Response(200, json={"forge": {"available": forge}})
        if p == "/v1/chains":
            return httpx.Response(200, json=[{"chain_id": 31337, "rpc_configured": rpc}])
        if p == "/v1/scans" and m == "POST":
            assert json.loads(req.content)["hook_address"] == HOOK
            return httpx.Response(202, json={"id": "s1", "status": "queued"})
        if p == "/v1/scans/s1":
            return httpx.Response(200, json={"id": "s1", "status": "completed", "block_number": 10, "hook_address": HOOK,
                                             "pools": [{"pool_id": POOL, "state": {"liquidity": "5"}}]})  # fmt: skip
        if p == "/v1/scans/s1/simulations":
            assert json.loads(req.content)["pool_id"] == POOL
            return httpx.Response(202, json={"id": "m1", "status": "queued"})
        if p == "/v1/simulations/m1":
            return httpx.Response(200, json={"id": "m1", "status": "completed", "fork_block": 10, "runs": runs})
        if p.startswith("/v1/simulations/m1/runs/"):
            rid = p.rsplit("/", 1)[1]
            r = next(x for x in runs if x["id"] == rid)
            return httpx.Response(200, json=r | {"steps": [{"name": "remove_full", "step_status": "passed",
                                                            "revert": {"message": "Paused()"}}]})  # fmt: skip
        if p == "/v1/scans/s1/findings":
            return httpx.Response(200, json=[{"id": "f"}])
        return httpx.Response(404, json={"code": "not_found", "message": p})

    return httpx.MockTransport(handler)


def go(transport: httpx.MockTransport, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = dict(
        api="http://hl.test",
        chain_id=31337,
        hook=HOOK,
        pool_id=None,
        block=None,
        scenarios=None,
        timeout_s=30,
        progress=lambda m: None,
    )
    args.update(kw)
    return lab.run_lab(transport=transport, **args)


def test_lab_flow_reports_server_results_verbatim() -> None:
    res = go(api())
    assert res["kind"] == "execution-tested"
    assert res["pool_id"] == POOL and res["fork_block"] == 10
    assert [(r["scenario_id"], r["status"]) for r in res["runs"]] == [
        ("withdrawal_failure", "passed"),
        ("oracle_failure", "unsupported"),
    ]
    assert res["runs"][0]["steps"][0]["revert"] == "Paused()"
    assert res["runs"][1]["steps"] == []  # unsupported runs are not fetched or embellished
    assert lab.lab_exit_code(res, fail_on_failed=True) == 0


def test_lab_failed_run_gate() -> None:
    res = go(
        api(runs=[{"id": "r1", "scenario_id": "withdrawal_failure", "status": "failed", "status_reason": "reverted"}])
    )
    assert lab.lab_exit_code(res, fail_on_failed=True) == 1
    assert lab.lab_exit_code(res, fail_on_failed=False) == 0


def test_lab_unavailable_without_forge_or_rpc() -> None:
    with pytest.raises(AnalysisError, match="forge"):
        go(api(forge=False))
    with pytest.raises(AnalysisError, match="no RPC endpoint"):
        go(api(rpc=False))


def test_lab_validation_and_unreachable_server() -> None:
    with pytest.raises(ConfigError):
        go(api(), scenarios=["made_up"])
    with pytest.raises(ConfigError):
        go(api(), chain_id=999)

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(SourceError, match="unreachable"):
        go(httpx.MockTransport(down))
