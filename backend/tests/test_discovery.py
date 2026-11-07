"""Pool discovery fallbacks: RPC provider error classification and Etherscan log paging (mocked HTTP)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.chains import ChainConfig
from app.services.pools import INITIALIZE_TOPIC, discover_pools_etherscan
from app.services.rpc import LogRangeTooLarge, RpcClient

HOOK = "0xf980f489ecc905efD2d8eE9d78faE5bf01FEc0C4"
OTHER = "0x0000000000000000000000000000000000001234"
PM = "0xE03A1074c86CFeDd5C142C4F04F1a1536e203543"


def _chain(rpc_url: str | None = "https://rpc.invalid") -> ChainConfig:
    return ChainConfig(
        chain_id=11155111,
        name="Sepolia Testnet",
        short_name="sepolia",
        native_symbol="ETH",
        pool_manager=PM,
        pool_manager_deploy_block=100,
        explorer_name=None,
        explorer_url=None,
        rpc_url=rpc_url,
    )


def _word(v: int) -> str:
    return v.to_bytes(32, "big", signed=v < 0).hex()


def _log(block: int, idx: int, hook: str, pool_byte: int) -> dict[str, Any]:
    data = "0x" + _word(3000) + _word(60) + hook[2:].lower().rjust(64, "0") + _word(2**96) + _word(0)
    return {
        "address": PM,
        "topics": [
            INITIALIZE_TOPIC,
            "0x" + f"{pool_byte:02x}" * 32,
            "0x" + "00" * 12 + "11" * 20,
            "0x" + "00" * 12 + "22" * 20,
        ],
        "data": data,
        "blockNumber": hex(block),
        "transactionHash": f"0x{block:064x}",
        "logIndex": hex(idx),
    }


def test_rpc_http_400_with_json_rpc_body_is_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32600, "message": "you can make eth_getLogs requests with up to a 10 block range"},
            },
        )

    with RpcClient(_chain(), transport=httpx.MockTransport(handler)) as rpc, pytest.raises(LogRangeTooLarge):
        rpc.call("eth_getLogs", [{}])


def test_etherscan_discovery_pages_by_block_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.pools as pools

    monkeypatch.setattr(pools, "ETHERSCAN_PAGE", 3)
    monkeypatch.setattr(pools.time, "sleep", lambda _s: None)
    monkeypatch.setenv("HOOKLENS_ETHERSCAN_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()
    # Five Initialize logs; block 120 holds two (one is the page boundary), two belong to HOOK.
    logs = [
        _log(110, 0, OTHER, 1),
        _log(120, 0, HOOK, 2),
        _log(120, 1, OTHER, 3),
        _log(130, 0, OTHER, 4),
        _log(140, 0, HOOK, 5),
    ]
    seen_from: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        assert q["module"] == "logs" and q["chainid"] == "11155111" and q["topic0"] == INITIALIZE_TOPIC
        frm = int(q["fromBlock"])
        seen_from.append(frm)
        page = [entry for entry in logs if int(entry["blockNumber"], 16) >= frm][:3]
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": page})

    try:
        res = discover_pools_etherscan(_chain(), HOOK, 200, transport=httpx.MockTransport(handler))
    finally:
        get_settings.cache_clear()
    assert res.status == "complete" and res.source == "etherscan"
    assert [p.pool_id[-2:] for p in res.pools] == ["02", "05"]  # each pool once, despite the overlap
    # Each full page restarts at the last block of the previous one; the short page at 130 is
    # confirmed as the end by one more query for the rest of the range.
    assert seen_from == [100, 120, 130, 141]
    assert res.scanned_to == 200


def test_etherscan_short_page_is_not_taken_as_the_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """A truncated (short) page must not end discovery: pools after it were silently missed before."""
    import app.services.pools as pools

    monkeypatch.setattr(pools, "ETHERSCAN_PAGE", 3)
    monkeypatch.setattr(pools.time, "sleep", lambda _s: None)
    monkeypatch.setenv("HOOKLENS_ETHERSCAN_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()
    logs = [_log(110, 0, HOOK, 1), _log(120, 0, OTHER, 2), _log(150, 0, HOOK, 3), _log(160, 0, HOOK, 4)]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        frm = int(request.url.params["fromBlock"])
        page = [e for e in logs if int(e["blockNumber"], 16) >= frm]
        if calls == 1:
            page = page[:2]  # the service returns fewer records than exist (truncated response)
        if not page:
            return httpx.Response(200, json={"status": "0", "message": "No records found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": page[:3]})

    try:
        res = discover_pools_etherscan(_chain(), HOOK, 200, transport=httpx.MockTransport(handler))
    finally:
        get_settings.cache_clear()
    assert res.status == "complete" and res.scanned_to == 200
    assert [p.pool_id[-2:] for p in res.pools] == ["01", "03", "04"]


def test_discovery_without_hook_collects_every_hooked_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.pools as pools

    monkeypatch.setattr(pools.time, "sleep", lambda _s: None)
    monkeypatch.setenv("HOOKLENS_ETHERSCAN_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()
    logs = [_log(110, 0, HOOK, 1), _log(120, 0, OTHER, 2), _log(130, 0, "0x" + "0" * 40, 3)]

    def handler(request: httpx.Request) -> httpx.Response:
        frm = int(request.url.params["fromBlock"])
        page = [e for e in logs if int(e["blockNumber"], 16) >= frm]
        if not page:
            return httpx.Response(200, json={"status": "0", "message": "No records found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": page})

    try:
        res = discover_pools_etherscan(_chain(), None, 200, transport=httpx.MockTransport(handler), from_block=105)
    finally:
        get_settings.cache_clear()
    assert [p.pool_id[-2:] for p in res.pools] == ["01", "02"]  # hookless pool excluded
    assert res.from_block == 105


def test_etherscan_no_records_is_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLENS_ETHERSCAN_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "0", "message": "No records found", "result": []})

    try:
        res = discover_pools_etherscan(_chain(), HOOK, 200, transport=httpx.MockTransport(handler))
    finally:
        get_settings.cache_clear()
    assert res.status == "complete" and res.pools == []
