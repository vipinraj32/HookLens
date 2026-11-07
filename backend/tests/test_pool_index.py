"""The persistent pool index: fill once, then fetch only new blocks; never claim coverage it lacks."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

import app.services.pool_index as pi
from app.chains import ChainConfig
from app.db.base import session_scope
from app.db.models import PoolIndexCursor
from app.services.pools import DiscoveryResult, PoolInfo

HOOK = "0xf980f489ecc905efD2d8eE9d78faE5bf01FEc0C4"
OTHER = "0x0000000000000000000000000000000000001234"


def _chain(chain_id: int, pm: str = "0xE03A1074c86CFeDd5C142C4F04F1a1536e203543") -> ChainConfig:
    return ChainConfig(
        chain_id=chain_id,
        name="Test",
        short_name="test",
        native_symbol="ETH",
        pool_manager=pm,
        pool_manager_deploy_block=100,
        explorer_name=None,
        explorer_url=None,
        rpc_url="https://rpc.invalid",
    )


def _pool(n: int, hook: str, block: int) -> PoolInfo:
    return PoolInfo(
        pool_id="0x" + f"{n:02x}" * 32,
        currency0="0x" + "11" * 20,
        currency1="0x" + "22" * 20,
        fee=3000,
        tick_spacing=60,
        hooks=hook,
        init_sqrt_price_x96=2**96,
        init_tick=0,
        init_block=block,
        init_tx=None,
    )


class FakeLogs:
    """Stands in for discover_pools(hook=None): every hooked pool in [from_block, to_block]."""

    def __init__(self, pools: list[PoolInfo], fail_after: int | None = None) -> None:
        self.pools = pools
        self.calls: list[tuple[int, int]] = []
        self.fail_after = fail_after

    def __call__(self, rpc: Any, chain: ChainConfig, hook: Any, to_block: int, **kw: Any) -> DiscoveryResult:
        assert hook is None
        frm = kw["from_block"]
        self.calls.append((frm, to_block))
        end = to_block if self.fail_after is None else min(to_block, self.fail_after)
        res = DiscoveryResult(from_block=frm, to_block=to_block, scanned_to=end, source="etherscan")
        res.pools = [p for p in self.pools if frm <= p.init_block <= end]
        if end < to_block:
            res.status, res.reason = "partial", "Etherscan log query failed (rate limit or service error)."
        return res


@pytest.fixture()
def logs(monkeypatch: pytest.MonkeyPatch) -> FakeLogs:
    fake = FakeLogs([_pool(1, HOOK, 150), _pool(2, OTHER, 160), _pool(3, HOOK, 400), _pool(4, HOOK, 900)])
    monkeypatch.setattr(pi, "discover_pools", fake)
    return fake


def test_fills_once_then_reads_only_new_blocks(logs: FakeLogs) -> None:
    chain = _chain(990001)
    r1 = pi.discover_with_index(None, chain, HOOK, 500)  # type: ignore[arg-type]
    assert [p.pool_id[-2:] for p in r1.pools] == ["01", "03"]
    assert r1.status == "complete" and r1.source == "index" and r1.scanned_to == 500
    assert logs.calls == [(100, 500)]

    # Same pinned block (another hook): served from the index, no log query.
    r2 = pi.discover_with_index(None, chain, OTHER, 500)  # type: ignore[arg-type]
    assert [p.pool_id[-2:] for p in r2.pools] == ["02"] and len(logs.calls) == 1
    assert "no logs were fetched" in r2.notes[0]

    # A later block re-reads only the reorg margin plus the new range.
    r3 = pi.discover_with_index(None, chain, HOOK, 1000)  # type: ignore[arg-type]
    assert logs.calls[-1] == (500 - pi.REORG_MARGIN + 1, 1000)
    assert [p.pool_id[-2:] for p in r3.pools] == ["01", "03", "04"]


def test_pools_after_the_pinned_block_are_excluded(logs: FakeLogs) -> None:
    chain = _chain(990002)
    pi.discover_with_index(None, chain, HOOK, 1000)  # type: ignore[arg-type]
    older = pi.discover_with_index(None, chain, HOOK, 450)  # type: ignore[arg-type]
    assert [p.pool_id[-2:] for p in older.pools] == ["01", "03"] and older.status == "complete"


def test_incomplete_log_scan_is_reported_and_not_counted_as_covered(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLogs([_pool(1, HOOK, 150), _pool(3, HOOK, 400)], fail_after=300)
    monkeypatch.setattr(pi, "discover_pools", fake)
    chain = _chain(990003)
    r = pi.discover_with_index(None, chain, HOOK, 500)  # type: ignore[arg-type]
    assert r.status == "partial" and r.scanned_to == 300
    assert "covers blocks up to 300" in (r.reason or "")
    with session_scope() as db:
        cur = db.get(PoolIndexCursor, 990003)
        assert cur is not None and cur.scanned_to == 300

    # The next scan resumes from the gap instead of trusting the earlier partial result.
    fake.fail_after = None
    r2 = pi.discover_with_index(None, chain, HOOK, 500)  # type: ignore[arg-type]
    assert fake.calls[-1][0] == 300 - pi.REORG_MARGIN + 1
    assert r2.status == "complete" and [p.pool_id[-2:] for p in r2.pools] == ["01", "03"]


def test_a_different_pool_manager_rebuilds_the_index(logs: FakeLogs) -> None:
    pi.discover_with_index(None, _chain(990004), HOOK, 500)  # type: ignore[arg-type]
    moved = dataclasses.replace(_chain(990004), pool_manager="0x" + "ab" * 20)
    pi.discover_with_index(None, moved, HOOK, 500)  # type: ignore[arg-type]
    assert logs.calls[-1] == (100, 500)  # started over from the deploy block
