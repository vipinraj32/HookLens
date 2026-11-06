"""`hooklens lab`: execution testing through a HookLens server.

Execution testing is deliberately separate from the static scan. It needs a deployed hook, an
RPC endpoint and Foundry/Anvil, all of which live in the HookLens API + simulation worker (see
docs/deployment.md). This client asks that server to:

1. resolve the deployed hook at a pinned block (and discover its pools),
2. fork the chain at that block and run the controlled HookLens scenarios against the real
   PoolManager and hook (forge + anvil, server side),
3. return every run's status, revert reasons, token movements and reproduction command.

Nothing is simulated locally and no result is invented: a scenario the server cannot run is
reported with the status the server gives it (unsupported, skipped, infra_error, ...).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from hooklens.errors import AnalysisError, ConfigError, SourceError

SCENARIOS = (
    "withdrawal_failure",
    "oracle_failure",
    "fee_escalation",
    "admin_upgrade",
    "accounting_invariants",
    "transaction_ordering",
)
TERMINAL = {"completed", "partial", "failed", "cancelled", "timed_out", "infra_error"}
BAD_RUN = {"failed", "unexpected_revert"}


class LabClient:
    def __init__(self, api: str, *, timeout: float = 30.0, transport: httpx.BaseTransport | None = None) -> None:
        base = api.rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise ConfigError(f"--api must be an http(s) URL (got {api}).")
        self.base = base if base.endswith("/v1") else base + "/v1"
        # One client = one anonymous workspace cookie, so the scan and its simulation stay linked.
        self.c = httpx.Client(timeout=timeout, transport=transport, headers={"User-Agent": "hooklens-cli"})

    def close(self) -> None:
        self.c.close()

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self.c.request(method, self.base + path, **kw)
        except httpx.HTTPError as e:
            raise SourceError(
                f"HookLens server at {self.base} is unreachable ({type(e).__name__}).",
                hint="Start the HookLens API (see docs/deployment.md) or pass --api.",
            ) from e
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {}
            msg = body.get("detail") or body.get("message") or r.text[:300]
            code = body.get("code") or f"http_{r.status_code}"
            err = ConfigError if r.status_code in (400, 404, 422) else AnalysisError
            raise err(f"HookLens server rejected the request ({code}): {msg}")
        return r.json()

    def health(self) -> dict[str, Any]:
        out: dict[str, Any] = self._req("GET", "/health")
        return out

    def chain(self, chain_id: int) -> dict[str, Any] | None:
        chains = self._req("GET", "/chains")
        items = chains.get("items", chains) if isinstance(chains, dict) else chains
        return next((c for c in items if int(c.get("chain_id", -1)) == chain_id), None)

    def wait(self, path: str, timeout_s: int, on_tick: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        t0 = time.time()
        while True:
            obj: dict[str, Any] = self._req("GET", path)
            on_tick(obj)
            if obj.get("status") not in ("queued", "running"):
                return obj
            if time.time() - t0 > timeout_s:
                raise AnalysisError(f"Timed out after {timeout_s}s waiting for {path}.", hint="Raise --timeout.")
            time.sleep(3)


def run_lab(
    *,
    api: str,
    chain_id: int,
    hook: str,
    pool_id: str | None,
    block: int | None,
    scenarios: list[str] | None,
    timeout_s: int,
    progress: Callable[[str], None],
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    for s in scenarios or []:
        if s not in SCENARIOS:
            raise ConfigError(f"Unknown scenario '{s}'.", hint=f"Valid: {', '.join(SCENARIOS)}.")
    lab = LabClient(api, transport=transport)
    try:
        lab.health()
        worker = lab._req("GET", "/health/worker")
        if not ((worker.get("forge") or {}).get("available")):
            raise AnalysisError(
                "Execution testing is unavailable: the HookLens server has no forge binary for fork simulation.",
                hint="Install Foundry on the simulation worker (docker compose ships it in the sim-worker image).",
            )
        ch = lab.chain(chain_id)
        if ch is None:
            raise ConfigError(f"The HookLens server does not support chain {chain_id}.")
        if not ch.get("rpc_configured", True):
            raise AnalysisError(
                f"The HookLens server has no RPC endpoint configured for chain {chain_id}; execution testing is "
                "unavailable.",
                hint="Configure the chain's RPC URL on the server (see .env.example).",
            )
        body: dict[str, Any] = {"chain_id": chain_id, "hook_address": hook}
        if pool_id:
            body["pool_id"] = pool_id
        if block is not None:
            body["block_number"] = block
        progress(f"Resolving {hook} on chain {chain_id}")
        scan = lab._req("POST", "/scans", json=body)
        scan = lab.wait(f"/scans/{scan['id']}", timeout_s, lambda s: None)
        if scan["status"] not in ("completed", "partial"):
            err = scan.get("error") or {}
            raise AnalysisError(f"Server-side scan {scan['status']}: {err.get('message') or 'no details'}")
        pools = scan.get("pools") or []
        chosen = pool_id
        if not chosen:
            live = [p for p in pools if int(((p.get("state") or {}).get("liquidity")) or 0) > 0]
            if not (live or pools):
                raise AnalysisError(
                    "No pool using this hook was found; scenarios need a pool to execute.",
                    hint="Pass --pool-id for a specific pool.",
                )
            chosen = (live or pools)[0]["pool_id"]
        progress(f"Scan {scan['id']} pinned block {scan.get('block_number')}; simulating pool {chosen}")
        sim_body: dict[str, Any] = {"pool_id": chosen}
        if scenarios:
            sim_body["scenarios"] = scenarios
        sim = lab._req("POST", f"/scans/{scan['id']}/simulations", json=sim_body)
        seen: set[str] = set()

        def tick(s: dict[str, Any]) -> None:
            for r in s.get("runs") or []:
                key = f"{r['id']}:{r['status']}"
                if r["status"] not in ("queued", "running") and key not in seen:
                    seen.add(key)
                    progress(f"  {r['scenario_id']}: {r['status']}")

        sim = lab.wait(f"/simulations/{sim['id']}", timeout_s, tick)
        runs = []
        for r in sim.get("runs") or []:
            detail = r
            if r["status"] not in ("queued", "skipped", "unsupported"):
                detail = lab._req("GET", f"/simulations/{sim['id']}/runs/{r['id']}")
            runs.append(_run_record(detail))
        return {
            "kind": "execution-tested",
            "note": "Results of controlled scenarios executed on a fork at a pinned block by the HookLens "
            "simulation worker. They describe this fork, block and parameter set only.",
            "server": lab.base,
            "chain_id": chain_id,
            "hook": scan.get("hook_address") or hook,
            "scan_id": scan["id"],
            "block_number": scan.get("block_number"),
            "simulation_id": sim["id"],
            "simulation_status": sim["status"],
            "fork_block": sim.get("fork_block"),
            "fork_block_hash": sim.get("fork_block_hash"),
            "pool_id": chosen,
            "harness_version": sim.get("harness_version"),
            "error": sim.get("error"),
            "runs": runs,
            "static_findings": len(lab._req("GET", f"/scans/{scan['id']}/findings")),
        }
    finally:
        lab.close()


def _run_record(r: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for st in r.get("steps") or []:
        steps.append(
            {
                "name": st.get("name"),
                "status": st.get("step_status") or st.get("status"),
                "expected": st.get("lp_expectation"),
                "observed": st.get("observed"),
                "revert": (st.get("revert") or {}).get("message"),
            }
        )
    return {
        "scenario_id": r.get("scenario_id"),
        "status": r.get("status"),
        "status_reason": r.get("status_reason"),
        "repro_command": r.get("repro_command"),
        "duration_ms": r.get("duration_ms"),
        "error": r.get("error"),
        "steps": steps,
    }


def lab_exit_code(result: dict[str, Any], fail_on_failed: bool) -> int:
    if result.get("simulation_status") in ("infra_error", "failed", "timed_out", "cancelled") and not result["runs"]:
        return 4
    if fail_on_failed and any(r["status"] in BAD_RUN for r in result["runs"]):
        return 1
    return 0
