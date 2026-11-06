"""Job state machine and HTTP API behaviour that needs no chain."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.db.base import session_scope
from app.db.models import Job, utcnow
from app.errors import AppError
from app.jobs import manager
from app.jobs.manager import create_job, execute_job, register, request_cancel


def _job(kind: str, max_attempts: int = 2, timeout_s: int = 30) -> str:
    with session_scope() as db:
        return create_job(
            db,
            kind=kind,
            workspace_id="ws",
            subject_id=None,
            payload={},
            timeout_s=timeout_s,
            max_attempts=max_attempts,
        ).id


def _status(job_id: str) -> Job:
    with session_scope() as db:
        j = db.get(Job, job_id)
        assert j is not None
        db.expunge(j)
        return j


@register("t_ok")
def _ok(jc: manager.JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    jc.update("work", 0.5, "halfway")
    return {"message": "done"}


@register("t_fail")
def _fail(jc: manager.JobContext, payload: dict[str, Any]) -> None:
    raise AppError("boom", "deterministic failure", status_code=422)


@register("t_crash")
def _crash(jc: manager.JobContext, payload: dict[str, Any]) -> None:
    raise RuntimeError("secret internal detail")


@register("t_timeout")
def _timeout(jc: manager.JobContext, payload: dict[str, Any]) -> None:
    jc.deadline = 0
    jc.check()


def test_job_success_records_events() -> None:
    jid = _job("t_ok")
    assert execute_job(jid) == "succeeded"
    j = _status(jid)
    assert j.progress == 1.0 and [e["stage"] for e in j.events][:2] == ["queued", "work"]


def test_job_failure_and_crash_are_safe() -> None:
    jid = _job("t_fail")
    assert execute_job(jid) == "failed"
    assert _status(jid).error["code"] == "boom"
    jid = _job("t_crash")
    assert execute_job(jid) == "failed"
    err = _status(jid).error
    assert err["code"] == "internal_error" and "secret" not in str(err)


def test_job_timeout_and_cancel() -> None:
    jid = _job("t_timeout")
    assert execute_job(jid) == "timed_out"
    jid = _job("t_ok")
    with session_scope() as db:
        request_cancel(db, db.get(Job, jid))
    assert _status(jid).status == "cancelled"
    assert execute_job(jid) == "cancelled"


def test_reaper_marks_lost_workers() -> None:
    jid = _job("t_ok")
    with session_scope() as db:
        j = db.get(Job, jid)
        j.status, j.heartbeat_at = "running", utcnow() - timedelta(hours=1)
    assert manager.reap_stale_jobs() >= 1
    assert _status(jid).error["code"] == "worker_lost"


def test_unknown_job_kind() -> None:
    jid = _job("does_not_exist")
    assert execute_job(jid) == "failed"


# ---------------------------------------------------------------- HTTP


def test_health_and_chains(client: Any) -> None:
    assert client.get("/v1/health").json()["status"] == "ok"
    chains = {c["chain_id"]: c for c in client.get("/v1/chains").json()}
    assert chains[1]["rpc_configured"] is False and "rpc_url" not in chains[1]
    assert 31337 in chains
    r = client.get("/v1/health")
    assert r.headers["X-Correlation-ID"] and r.headers["X-Content-Type-Options"] == "nosniff"


def test_problem_json_errors(client: Any) -> None:
    r = client.post("/v1/scans", json={"chain_id": 5, "hook_address": "0x" + "11" * 20})
    assert r.status_code == 422 and r.json()["code"] == "unsupported_chain"
    assert r.headers["content-type"].startswith("application/problem+json")
    r = client.post("/v1/scans", json={"chain_id": 1, "hook_address": "0x" + "11" * 20})
    assert r.status_code == 503 and r.json()["code"] == "rpc_not_configured"
    r = client.post("/v1/scans", json={"chain_id": 31337, "hook_address": "0x" + "00" * 20})
    assert r.status_code == 422
    r = client.post("/v1/scans", json={"chain_id": 31337, "hook_address": "not-an-address-but-42-characters-long!!!!!"})
    assert r.status_code == 422
    r = client.get("/v1/scans/does-not-exist")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_workspace_tokens(client: Any) -> None:
    r = client.get("/v1/scans")
    token = r.headers["X-HookLens-Workspace"]
    assert "." in token
    r2 = client.get("/v1/scans", headers={"X-HookLens-Workspace": token})
    assert r2.headers["X-HookLens-Workspace"] == token
    forged = token.split(".")[0] + ".00000000000000000000000000000000"
    r3 = client.get("/v1/scans", headers={"X-HookLens-Workspace": forged})
    assert r3.status_code == 401


def test_permission_decode_endpoint(client: Any) -> None:
    r = client.get("/v1/permissions/decode", params={"address": "0x9d536C7335f6ca4D20384AaF7F655eb364B00200"})
    assert r.json()["enabled_flags"] == ["BEFORE_REMOVE_LIQUIDITY"]


def test_scenario_catalogue(client: Any) -> None:
    ids = [s["scenario_id"] for s in client.get("/v1/scenarios").json()]
    assert set(ids) == {
        "withdrawal_failure",
        "oracle_failure",
        "fee_escalation",
        "admin_upgrade",
        "accounting_invariants",
        "transaction_ordering",
    }


def test_rate_limiter() -> None:
    from app.api.security import RateLimiter

    rl = RateLimiter()
    for _ in range(3):
        rl.check("c", "b", 3)
    with pytest.raises(AppError) as e:
        rl.check("c", "b", 3)
    assert e.value.status_code == 429


def test_secret_redaction() -> None:
    from app.observability import redact

    s = redact("GET https://eth-mainnet.g.alchemy.com/v2/abcdefghijklmnopqrstuvwxyz123456 apikey=SECRET1 sk-ant-xyz")
    assert "abcdefghijklmnop" not in s and "SECRET1" not in s and "sk-ant-xyz" not in s


def test_compare_rejects_impossible_price_moves(client: Any) -> None:
    # A move of -100% or worse has no meaning; it must be rejected, not silently dropped.
    r = client.post("/v1/positions/compare", json={"scan_id": "x", "price_moves": [-1.0]})
    assert r.status_code == 422
    r = client.post("/v1/positions/compare", json={"scan_id": "x", "price_moves": [-2]})
    assert r.status_code == 422


def test_production_requires_a_real_workspace_secret() -> None:
    from pydantic import ValidationError

    from app.config import Settings

    # _env_file=None: judge the guard itself, not whatever secret a developer's .env provides.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", workspace_secret="short")
    assert Settings(_env_file=None, environment="production", workspace_secret="x" * 40).environment == "production"


def test_simulations_route_to_the_hardened_queue() -> None:
    from app.jobs.dispatch import queue_for

    assert queue_for("simulation") == "sim"
    assert {queue_for(k) for k in ("scan", "report", "explain", None)} == {"default"}


def test_blank_env_values_mean_unset() -> None:
    from app.config import Settings

    s = Settings(mainnet_rpc_url="", etherscan_api_key=" ", anthropic_api_key="", workspace_secret="")
    assert s.mainnet_rpc_url is None and s.etherscan_api_key is None and not s.ai_enabled
    assert len(s.workspace_secret.get_secret_value()) >= 32


def test_sepolia_chain_registry() -> None:
    from app.chains import SEPOLIA_POOL_MANAGER, load_chains
    from app.config import Settings

    off = load_chains(Settings(sepolia_rpc_url=""))[11155111]
    assert off.pool_manager == SEPOLIA_POOL_MANAGER and not off.rpc_configured
    assert any("HOOKLENS_SEPOLIA_RPC_URL" in n for n in off.notes)

    on = load_chains(Settings(sepolia_rpc_url="https://sepolia.example/v3/abcdefghijklmnopqrstuvwxyz"))[11155111]
    assert on.rpc_configured and on.pool_manager_deploy_block == 7_258_946
    public = on.public_dict()
    assert "rpc_url" not in public and "abcdefghij" not in str(public)  # the RPC URL never leaves the server
    assert public["source_verification"] == "etherscan"


def test_cors_origins_from_env_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    monkeypatch.setenv("HOOKLENS_CORS_ORIGINS", "http://localhost:3000, https://app.example")
    assert Settings().cors_origins == ["http://localhost:3000", "https://app.example"]
