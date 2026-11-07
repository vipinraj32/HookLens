"""End-to-end against a local Anvil with the HookLens fixtures deployed and real forge runs.

scripts/dev-chain.sh            # anvil + fixture deployment
uv run pytest -m anvil
"""

from __future__ import annotations

import time
from typing import Any

import pytest

pytestmark = [pytest.mark.anvil]


def _wait(client: Any, job_id: str, timeout: float = 300) -> dict:
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/v1/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed", "cancelled", "timed_out"):
            return j
        time.sleep(0.3)
    raise AssertionError("job did not finish")


def _scan(client: Any, address: str) -> dict:
    r = client.post("/v1/scans", json={"chain_id": 31337, "hook_address": address})
    assert r.status_code == 202, r.text
    scan = r.json()
    job = _wait(client, scan["job_id"])
    assert job["status"] == "succeeded", job
    return client.get(f"/v1/scans/{scan['id']}").json()


def test_resolver_detects_proxy(client: Any, deployments: dict) -> None:
    r = client.post(
        "/v1/hooks/resolve", json={"chain_id": 31337, "address": deployments["hook_pausable_proxy"]["address"]}
    )
    body = r.json()
    assert body["proxy"]["is_proxy"] and body["proxy"]["kind"] == "eip1967"
    assert body["proxy"]["implementation"].lower() == deployments["pausable_implementation"].lower()
    assert body["source_status"] == "local-artifact"


def test_eoa_and_empty_address_rejected(client: Any, deployments: dict) -> None:
    r = client.post("/v1/hooks/resolve", json={"chain_id": 31337, "address": deployments["deployer"]})
    assert r.status_code == 422


def test_oracle_hook_scan_findings_and_evidence(client: Any, deployments: dict) -> None:
    scan = _scan(client, deployments["hook_oracle_gated"]["address"])
    assert scan["status"] == "completed"
    assert scan["permissions"]["enabled_flags"] == ["BEFORE_REMOVE_LIQUIDITY"]
    assert len(scan["pools"]) == 1 and scan["pools"][0]["state"]["initialized"]
    findings = client.get(f"/v1/scans/{scan['id']}/findings").json()
    rules = {f["rule_id"] for f in findings}
    assert {"oracle_dependency", "oracle_replaceable"} <= rules
    for f in findings:  # every finding's evidence exists
        ids = ",".join(f["evidence_ids"])
        ev = client.get("/v1/evidence", params={"scan_id": scan["id"], "ids": ids}).json()
        assert ev["total"] == len(f["evidence_ids"])
    # stable IDs: a second scan of the same hook yields identical finding IDs
    scan2 = _scan(client, deployments["hook_oracle_gated"]["address"])
    ids2 = {f["finding_id"] for f in client.get(f"/v1/scans/{scan2['id']}/findings").json()}
    assert ids2 == {f["finding_id"] for f in findings}


@pytest.mark.forge
def test_oracle_hook_simulation_lp_and_report(client: Any, deployments: dict) -> None:
    scan = _scan(client, deployments["hook_oracle_gated"]["address"])
    r = client.post(f"/v1/scans/{scan['id']}/simulations", json={"scenarios": ["withdrawal_failure", "fee_escalation"]})
    assert r.status_code == 202, r.text
    sim = r.json()
    assert {x["scenario_id"]: x["status"] for x in sim["runs"]}["fee_escalation"] == "unsupported"
    assert _wait(client, sim["job_id"])["status"] == "succeeded"
    sim = client.get(f"/v1/simulations/{sim['id']}").json()
    runs = {x["scenario_id"]: x for x in sim["runs"]}
    wd = runs["withdrawal_failure"]
    assert wd["status"] == "unexpected_revert"
    detail = client.get(f"/v1/simulations/{sim['id']}/runs/{wd['id']}").json()
    steps = {s["name"]: s for s in detail["steps"]}
    assert steps["full_remove"]["observed"] == "success"
    stale = steps["remove_under_oracle_stale"]
    assert stale["observed"] == "revert" and stale["revert"]["inner"]["name"] == "StaleOraclePrice"
    assert steps["recover_after_oracle_stale"]["observed"] == "success"
    assert detail["trace"]["nodes"] and stale["revert_chain"][-1]["label"] in ("Oracle", "Hook")
    assert "ETH_RPC_URL=<" in wd["repro_command"] and "127.0.0.1" not in wd["repro_command"]

    observed = client.get(f"/v1/scans/{scan['id']}/findings", params={"basis": "simulation"}).json()
    assert {f["rule_id"] for f in observed} >= {"withdrawal_blocked_oracle_revert", "withdrawal_blocked_oracle_stale"}

    # Express the range as USD per WETH whichever token sorts first.
    usd_is_token0 = scan["pools"][0]["token0"]["symbol"] == "hlUSD"
    lp = client.post(
        "/v1/positions/compare",
        json={
            "scan_id": scan["id"],
            "simulation_id": sim["id"],
            "price_lower": "1500",
            "price_upper": "2500",
            "price_orientation": "token0_per_token1" if usd_is_token0 else "token1_per_token0",
            "amount0": "2000" if usd_is_token0 else "1",
            "amount1": "1" if usd_is_token0 else "2000",
        },
    ).json()
    assert lp["baseline"]["range_state"]["value"] == "in-range"
    # Live state from the real node, at or after the scan's pinned block, with provenance.
    src = lp["data_source"]
    assert src["source"] == "live" and src["block_number"] >= scan["block_number"]
    assert src["block_hash"] and src["fetched_at"] and lp["baseline"]["price"]["tag"] == "live"
    # The oracle-gated hook accepts the deposit, so a removal that reverts is a genuine block.
    eff = lp["simulation_effects"]
    assert eff["position_creation"]["status"] == "created"
    assert {b["condition"] for b in eff["withdrawal_blocked_under"]} >= {"oracle_revert"}
    assert eff["withdrawal"]["status"] == "blocked"
    blocked = [o for o in eff["withdrawal"]["outcomes"] if o["outcome"] == "blocked"]
    assert blocked and all("CannotUpdateEmptyPosition" not in (o["revert"] or "") for o in blocked)
    live = client.get(f"/v1/scans/{scan['id']}/pools/{scan['pools'][0]['pool_id']}/live").json()
    assert live["source"] == "live" and live["chain_id"] == 31337 and live["block_hash"]
    assert lp["baseline"]["fee_income"]["tag"] == "unavailable"

    rep = client.post(
        f"/v1/scans/{scan['id']}/reports", json={"simulation_id": sim["id"], "position_id": lp["position_id"]}
    ).json()
    deadline = time.time() + 30
    while client.get(f"/v1/reports/{rep['id']}").json()["status"] == "rendering" and time.time() < deadline:
        time.sleep(0.2)
    full = client.get(f"/v1/reports/{rep['id']}").json()
    assert full["status"] == "ready" and full["content_hash"].startswith("sha256:")
    assert any(f["confidence_basis"] == "simulation" for f in full["content"]["findings"])
    pdf = client.get(f"/v1/reports/{rep['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


@pytest.mark.forge
def test_pausable_proxy_upgrade_blocks_withdrawal(client: Any, deployments: dict) -> None:
    scan = _scan(client, deployments["hook_pausable_proxy"]["address"])
    sim = client.post(
        f"/v1/scans/{scan['id']}/simulations", json={"scenarios": ["admin_upgrade", "withdrawal_failure"]}
    ).json()
    _wait(client, sim["job_id"])
    runs = {x["scenario_id"]: x for x in client.get(f"/v1/simulations/{sim['id']}").json()["runs"]}
    assert runs["admin_upgrade"]["status"] == "unexpected_revert"
    assert runs["withdrawal_failure"]["status"] == "unexpected_revert"
    rules = {
        f["rule_id"] for f in client.get(f"/v1/scans/{scan['id']}/findings", params={"basis": "simulation"}).json()
    }
    assert {
        "withdrawal_blocked_upgraded_implementation",
        "withdrawal_blocked_paused",
        "withdrawal_requires_owner_paused",
    } <= rules


@pytest.mark.forge
def test_dynamic_fee_escalation_measured(client: Any, deployments: dict) -> None:
    scan = _scan(client, deployments["hook_dynamic_fee"]["address"])
    sim = client.post(f"/v1/scans/{scan['id']}/simulations", json={"scenarios": ["fee_escalation"]}).json()
    _wait(client, sim["job_id"])
    obs = client.get(f"/v1/scans/{scan['id']}/findings", params={"basis": "simulation"}).json()
    fee = [f for f in obs if f["rule_id"] == "fee_raised_by_owner"]
    assert fee and "1000000 pips" in fee[0]["title"]


@pytest.mark.forge
def test_noop_hook_has_no_observed_findings(client: Any, deployments: dict) -> None:
    scan = _scan(client, deployments["hook_noop"]["address"])
    sim = client.post(f"/v1/scans/{scan['id']}/simulations", json={}).json()
    _wait(client, sim["job_id"])
    statuses = {x["scenario_id"]: x["status"] for x in client.get(f"/v1/simulations/{sim['id']}").json()["runs"]}
    assert statuses["withdrawal_failure"] == "passed" and statuses["accounting_invariants"] == "passed"
    assert statuses["oracle_failure"] == "unsupported"
    assert client.get(f"/v1/scans/{scan['id']}/findings", params={"basis": "simulation"}).json() == []
