"""Persistent per-chain index of hooked v4 pools.

`Initialize(id, currency0, currency1, fee, tickSpacing, hooks, ...)` does not index `hooks`, so the
pools of one hook can only be found by reading every `Initialize` log since the PoolManager was
deployed: minutes on a public chain. Those logs are immutable, so HookLens reads them once, stores
every pool that has a hook, and afterwards only reads the blocks added since. The cursor records the
contiguous block range the index covers; results are complete only up to it.

The last REORG_MARGIN blocks are re-read on the next update (entries are upserted), so a shallow
reorg cannot leave the cursor past a block whose logs changed. Local chains are never indexed: a
dev chain can be reset under the same chain id.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chains import ChainConfig
from app.db.base import session_scope
from app.db.models import PoolIndexCursor, PoolIndexEntry
from app.services.pools import DiscoveryResult, PoolInfo, discover_pools
from app.services.rpc import RpcClient

log = logging.getLogger(__name__)

REORG_MARGIN = 64
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(chain_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(chain_id, threading.Lock())


def _to_entry(chain_id: int, p: PoolInfo) -> PoolIndexEntry:
    return PoolIndexEntry(
        chain_id=chain_id,
        pool_id=p.pool_id.lower(),
        hooks=p.hooks.lower(),
        currency0=p.currency0,
        currency1=p.currency1,
        fee=p.fee,
        tick_spacing=p.tick_spacing,
        init_sqrt_price_x96=str(p.init_sqrt_price_x96),
        init_tick=p.init_tick,
        init_block=p.init_block,
        init_tx=p.init_tx,
    )


def _to_info(e: PoolIndexEntry) -> PoolInfo:
    from eth_utils import to_checksum_address

    return PoolInfo(
        pool_id=e.pool_id,
        currency0=e.currency0,
        currency1=e.currency1,
        fee=e.fee,
        tick_spacing=e.tick_spacing,
        hooks=to_checksum_address(e.hooks),
        init_sqrt_price_x96=int(e.init_sqrt_price_x96),
        init_tick=e.init_tick,
        init_block=e.init_block,
        init_tx=e.init_tx,
    )


def _store(db: Session, chain_id: int, pools: list[PoolInfo]) -> int:
    """Upsert pools; returns how many were new."""
    if not pools:
        return 0
    ids = {p.pool_id.lower() for p in pools}
    existing: set[str] = set()
    id_list = list(ids)
    for i in range(0, len(id_list), 500):
        chunk = id_list[i : i + 500]
        existing |= set(
            db.execute(
                select(PoolIndexEntry.pool_id).where(
                    PoolIndexEntry.chain_id == chain_id, PoolIndexEntry.pool_id.in_(chunk)
                )
            ).scalars()
        )
    new = 0
    for p in {p.pool_id.lower(): p for p in pools}.values():
        if p.pool_id.lower() in existing:
            continue
        db.add(_to_entry(chain_id, p))
        new += 1
    return new


def update_index(
    db: Session, rpc: RpcClient, chain: ChainConfig, to_block: int, should_stop: Any = None
) -> dict[str, Any]:
    """Bring the chain's index up to `to_block` (or as far as the providers allow)."""
    with _lock(chain.chain_id):
        cur = db.get(PoolIndexCursor, chain.chain_id)
        pm = (chain.pool_manager or "").lower()
        if cur is not None and cur.pool_manager != pm:
            # A different PoolManager means a different event stream: start over.
            db.query(PoolIndexEntry).filter(PoolIndexEntry.chain_id == chain.chain_id).delete()
            db.delete(cur)
            db.flush()
            cur = None
        start = (
            chain.pool_manager_deploy_block if cur is None else max(cur.from_block, cur.scanned_to - REORG_MARGIN + 1)
        )
        if cur is not None and cur.scanned_to >= to_block:
            return {"fetched": None, "new_pools": 0, "covered_to": cur.scanned_to, "source": cur.source}
        res: DiscoveryResult = discover_pools(rpc, chain, None, to_block, from_block=start, should_stop=should_stop)
        new = _store(db, chain.chain_id, res.pools)
        # Only a contiguous range starting at the old coverage counts as covered.
        covered = res.scanned_to if res.scanned_to >= start else (cur.scanned_to if cur else start - 1)
        if cur is None:
            cur = PoolIndexCursor(
                chain_id=chain.chain_id,
                pool_manager=pm,
                from_block=chain.pool_manager_deploy_block,
                scanned_to=covered,
                source=res.source,
            )
            db.add(cur)
        elif covered > cur.scanned_to:
            cur.scanned_to = covered
            cur.source = res.source
        db.commit()
        log.info(
            "pool index updated",
            extra={"chain_id": chain.chain_id, "from": start, "to": covered, "new_pools": new, "status": res.status},
        )
        return {
            "fetched": [start, res.scanned_to],
            "new_pools": new,
            "covered_to": cur.scanned_to,
            "source": res.source,
            "status": res.status,
            "reason": res.reason,
            "notes": res.notes,
        }


def discover_with_index(
    rpc: RpcClient, chain: ChainConfig, hook: str, block: int, should_stop: Any = None
) -> DiscoveryResult:
    """Pools of `hook` initialized at or before `block`, from the index (updated first if behind).

    Uses its own session so index commits never commit the caller's in-progress work.
    """
    with session_scope() as db:
        return _discover(db, rpc, chain, hook, block, should_stop)


def _discover(
    db: Session, rpc: RpcClient, chain: ChainConfig, hook: str, block: int, should_stop: Any
) -> DiscoveryResult:
    upd = update_index(db, rpc, chain, block, should_stop=should_stop)
    rows = (
        db.execute(
            select(PoolIndexEntry)
            .where(
                PoolIndexEntry.chain_id == chain.chain_id,
                PoolIndexEntry.hooks == hook.lower(),
                PoolIndexEntry.init_block <= block,
            )
            .order_by(PoolIndexEntry.init_block)
        )
        .scalars()
        .all()
    )
    covered = min(upd["covered_to"], block)
    res = DiscoveryResult(
        pools=[_to_info(r) for r in rows],
        from_block=chain.pool_manager_deploy_block,
        to_block=block,
        scanned_to=covered,
        source="index",
    )
    if upd["fetched"] is None:
        res.notes.append(f"Pool index already covered block {block}; no logs were fetched.")
    else:
        a, b = upd["fetched"]
        res.notes.append(
            f"Pool index updated with blocks {a}-{b} via {upd['source']} ({upd['new_pools']} new hooked pool(s))."
        )
        res.notes.extend(upd.get("notes") or [])
    if covered < block:
        res.status = "partial" if res.pools else "failed"
        res.reason = (upd.get("reason") or "Log scan incomplete.") + f" The pool index covers blocks up to {covered}."
    return res
