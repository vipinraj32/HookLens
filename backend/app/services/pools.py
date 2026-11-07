"""Uniswap v4 pool discovery and on-chain pool state.

Pools are discovered from PoolManager `Initialize` events (the hook address is not an indexed
topic, so logs are filtered client-side) in chunked block ranges. Pool state is read through
`extsload` using the StateLibrary storage layout of the pinned v4-core version.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from eth_abi import decode as abi_decode

from app.chains import ChainConfig
from app.config import get_settings
from app.errors import AppError, RpcError
from app.services.evm import ZERO_ADDRESS, hex_to_bytes, keccak, keccak_hex, selector, to_signed
from app.services.rpc import LogRangeTooLarge, RpcClient

log = logging.getLogger(__name__)

INITIALIZE_TOPIC = keccak_hex(b"Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)")
POOLS_SLOT = 6  # StateLibrary.POOLS_SLOT
LIQUIDITY_OFFSET = 3  # StateLibrary.LIQUIDITY_OFFSET
EXTSLOAD = selector("extsload(bytes32)")
DYNAMIC_FEE_FLAG = 0x800000


@dataclass
class PoolInfo:
    pool_id: str
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hooks: str
    init_sqrt_price_x96: int
    init_tick: int
    init_block: int
    init_tx: str | None

    @property
    def dynamic_fee(self) -> bool:
        return self.fee == DYNAMIC_FEE_FLAG

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "currency0": self.currency0,
            "currency1": self.currency1,
            "fee": self.fee,
            "dynamic_fee": self.dynamic_fee,
            "tick_spacing": self.tick_spacing,
            "hooks": self.hooks,
            "init_sqrt_price_x96": str(self.init_sqrt_price_x96),
            "init_tick": self.init_tick,
            "init_block": self.init_block,
            "init_tx": self.init_tx,
        }


@dataclass
class DiscoveryResult:
    pools: list[PoolInfo] = field(default_factory=list)
    status: str = "complete"  # complete | partial | failed | skipped
    from_block: int = 0
    to_block: int = 0
    scanned_to: int = 0
    reason: str | None = None
    source: str = "rpc"  # rpc | etherscan
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "notes": self.notes,
            "from_block": self.from_block,
            "to_block": self.to_block,
            "scanned_to": self.scanned_to,
            "reason": self.reason,
            "pool_count": len(self.pools),
        }


def _wanted(p: PoolInfo, hook: str | None) -> bool:
    """Pools for `hook`, or every pool with a hook (for the pool index) when `hook` is None."""
    if hook is None:
        return p.hooks.lower() != ZERO_ADDRESS
    return p.hooks.lower() == hook.lower()


def _parse_initialize(entry: dict[str, Any]) -> PoolInfo:
    topics = entry["topics"]
    data = hex_to_bytes(entry["data"])
    fee, tick_spacing, hooks, sqrt_price, tick = abi_decode(["uint24", "int24", "address", "uint160", "int24"], data)
    from eth_utils import to_checksum_address

    return PoolInfo(
        pool_id=topics[1].lower(),
        currency0=to_checksum_address("0x" + topics[2][-40:]),
        currency1=to_checksum_address("0x" + topics[3][-40:]),
        fee=int(fee),
        tick_spacing=int(tick_spacing),
        hooks=to_checksum_address(hooks),
        init_sqrt_price_x96=int(sqrt_price),
        init_tick=int(tick),
        init_block=int(entry["blockNumber"], 16),
        init_tx=entry.get("transactionHash"),
    )


def discover_pools(
    rpc: RpcClient,
    chain: ChainConfig,
    hook: str | None,
    to_block: int,
    *,
    pool_id: str | None = None,
    should_stop: Any = None,
    from_block: int | None = None,
) -> DiscoveryResult:
    if not chain.pool_manager:
        return DiscoveryResult(status="failed", reason="No PoolManager is configured for this chain.")
    s = get_settings()
    start = chain.pool_manager_deploy_block if from_block is None else from_block
    res = DiscoveryResult(from_block=start, to_block=to_block, scanned_to=start - 1)
    chunk = s.log_scan_chunk_blocks
    topics: list[Any] = [INITIALIZE_TOPIC] + ([pool_id] if pool_id else [])
    cur = start
    chunks = 0
    while cur <= to_block:
        if should_stop and should_stop():
            res.status, res.reason = "partial", "cancelled"
            return res
        if chunks >= s.log_scan_max_chunks:
            res.status = "partial"
            res.reason = (
                f"Stopped after {chunks} log queries (scan limit). Provide the pool ID to target a specific pool."
            )
            return res
        end = min(cur + chunk - 1, to_block)
        try:
            logs = rpc.get_logs(chain.pool_manager, topics, cur, end)
        except LogRangeTooLarge:
            if chunk <= 500:
                reason = "The RPC endpoint refuses even small eth_getLogs ranges (provider plan limit)."
                return _fallback(chain, hook, to_block, pool_id, should_stop, res, reason, start)
            chunk //= 4
            continue
        except RpcError as e:
            return _fallback(chain, hook, to_block, pool_id, should_stop, res, e.message, start)
        for entry in logs:
            try:
                p = _parse_initialize(entry)
            except (ValueError, KeyError, IndexError):
                continue
            if _wanted(p, hook):
                res.pools.append(p)
        res.scanned_to = end
        cur = end + 1
        chunks += 1
        if pool_id and res.pools:
            break
    return res


def _fallback(
    chain: ChainConfig,
    hook: str | None,
    to_block: int,
    pool_id: str | None,
    should_stop: Any,
    rpc_res: DiscoveryResult,
    rpc_reason: str,
    from_block: int,
) -> DiscoveryResult:
    """Use the explorer's log index when the RPC cannot serve the scan (e.g. free-tier range limits)."""
    s = get_settings()
    if chain.is_local or not s.etherscan_api_key:
        rpc_res.status = "partial" if rpc_res.pools else "failed"
        rpc_res.reason = rpc_reason + (
            "" if chain.is_local else " Set HOOKLENS_ETHERSCAN_API_KEY to discover pools through Etherscan instead."
        )
        return rpc_res
    res = discover_pools_etherscan(
        chain, hook, to_block, pool_id=pool_id, should_stop=should_stop, from_block=rpc_res.scanned_to + 1
    )
    res.from_block = from_block
    res.pools = rpc_res.pools + res.pools
    res.notes.insert(0, f"RPC log scan stopped ({rpc_reason}); pools were discovered through Etherscan instead.")
    return res


ETHERSCAN_PAGE = 1000
ETHERSCAN_MAX_REQUESTS = 300


def discover_pools_etherscan(
    chain: ChainConfig,
    hook: str | None,
    to_block: int,
    *,
    pool_id: str | None = None,
    should_stop: Any = None,
    transport: httpx.BaseTransport | None = None,
    from_block: int | None = None,
) -> DiscoveryResult:
    """Discover pools from Etherscan v2 `logs/getLogs`, paging forward by block.

    Each response holds at most ETHERSCAN_PAGE logs in block order, so the next window starts at the
    last block seen; logs repeated at that boundary are de-duplicated by (tx hash, log index).
    A short page is never taken as the end on its own: the scan is complete only once a query for
    the remaining range returns no records.
    """
    s = get_settings()
    start = chain.pool_manager_deploy_block if from_block is None else from_block
    res = DiscoveryResult(from_block=start, to_block=to_block, scanned_to=start - 1, source="etherscan")
    if not chain.pool_manager or not s.etherscan_api_key:
        res.status, res.reason = "failed", "Etherscan discovery needs a PoolManager and HOOKLENS_ETHERSCAN_API_KEY."
        return res
    params: dict[str, str] = {
        "chainid": str(chain.chain_id),
        "module": "logs",
        "action": "getLogs",
        "address": chain.pool_manager,
        "topic0": INITIALIZE_TOPIC,
        "page": "1",
        "offset": str(ETHERSCAN_PAGE),
        "apikey": s.etherscan_api_key.get_secret_value(),
    }
    if pool_id:
        params |= {"topic1": pool_id, "topic0_1_opr": "and"}
    seen: set[tuple[str, str]] = set()
    cur = start
    with httpx.Client(timeout=s.rpc_timeout_s, transport=transport) as client:
        for n in range(ETHERSCAN_MAX_REQUESTS):
            if should_stop and should_stop():
                res.status, res.reason = "partial", "cancelled"
                return res
            if n:
                time.sleep(0.22)  # stay under the free-tier limit of 5 requests/second
            body = _etherscan_get(
                client, s.etherscan_api_url, params | {"fromBlock": str(cur), "toBlock": str(to_block)}
            )
            if body is None:
                res.status = "partial" if res.pools else "failed"
                res.reason = "Etherscan log query failed (rate limit or service error)."
                return res
            result = body.get("result")
            if body.get("status") != "1" or not isinstance(result, list):
                if "no records" in str(body.get("message", "")).lower():
                    res.scanned_to = to_block
                    return res
                res.status = "partial" if res.pools else "failed"
                res.reason = f"Etherscan log query failed: {str(body.get('message') or result)[:160]}"
                return res
            if not result:
                res.scanned_to = to_block
                return res
            last_block = cur
            for entry in result:
                key = (str(entry.get("transactionHash")), str(entry.get("logIndex")))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    p = _parse_initialize(entry)
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                last_block = max(last_block, p.init_block)
                if _wanted(p, hook):
                    res.pools.append(p)
            if pool_id and res.pools:
                res.scanned_to = last_block
                return res
            if len(result) < ETHERSCAN_PAGE:
                # A short page holds every log up to its last block. Confirm the rest of the range is
                # empty instead of assuming it (a truncated response would otherwise end the scan early).
                res.scanned_to = last_block
                if last_block >= to_block:
                    return res
                cur = last_block + 1
                continue
            res.scanned_to = last_block - 1
            # Continue from the last block seen (it may hold more logs); never stall on one block.
            cur = last_block if last_block > cur else cur + 1
    res.status = "partial"
    res.reason = f"Stopped after {ETHERSCAN_MAX_REQUESTS} Etherscan log queries (scan limit)."
    return res


def _etherscan_get(client: httpx.Client, url: str, params: dict[str, str]) -> dict[str, Any] | None:
    delay = 1.0
    for _ in range(4):
        try:
            body = client.get(url, params=params).json()
        except (httpx.HTTPError, ValueError):
            body = None
        if isinstance(body, dict) and "rate limit" not in str(body.get("result", "")).lower():
            return body
        time.sleep(delay)
        delay *= 2
    return None


def _extsload(rpc: RpcClient, pm: str, slot: int, block: int) -> int:
    data = EXTSLOAD + slot.to_bytes(32, "big").hex()
    out = rpc.eth_call(pm, data, block)
    return int(out, 16) if out and out != "0x" else 0


def pool_state_slot(pool_id: str) -> int:
    return int.from_bytes(keccak(hex_to_bytes(pool_id).rjust(32, b"\x00") + POOLS_SLOT.to_bytes(32, "big")), "big")


def read_pool_state(rpc: RpcClient, pool_manager: str, pool_id: str, block: int) -> dict[str, Any]:
    """slot0 layout (StateLibrary.getSlot0): sqrtPriceX96 | tick(24) | protocolFee(24) | lpFee(24)."""
    base = pool_state_slot(pool_id)
    slot0 = _extsload(rpc, pool_manager, base, block)
    sqrt_price = slot0 & ((1 << 160) - 1)
    tick = to_signed((slot0 >> 160) & 0xFFFFFF, 24)
    protocol_fee = (slot0 >> 184) & 0xFFFFFF
    lp_fee = (slot0 >> 208) & 0xFFFFFF
    liquidity = _extsload(rpc, pool_manager, base + LIQUIDITY_OFFSET, block) & ((1 << 128) - 1)
    return {
        "initialized": sqrt_price != 0,
        "sqrt_price_x96": str(sqrt_price),
        "tick": tick,
        "protocol_fee": protocol_fee,
        "lp_fee": lp_fee,
        "liquidity": str(liquidity),
        "block_number": block,
    }


def token_metadata(rpc: RpcClient, token: str, block: int) -> dict[str, Any]:
    if token == ZERO_ADDRESS:
        return {"address": token, "symbol": "ETH", "decimals": 18, "native": True, "decimals_source": "native"}
    meta: dict[str, Any] = {"address": token, "native": False}
    try:
        out = rpc.try_call(token, selector("decimals()"), block)
        meta["decimals"] = int(out, 16) if out else None
        meta["decimals_source"] = "eth_call" if out else "unavailable"
        if meta["decimals"] is not None and meta["decimals"] > 77:
            meta["decimals"], meta["decimals_source"] = None, "invalid"
    except RpcError:
        meta["decimals"], meta["decimals_source"] = None, "unavailable"
    try:
        out = rpc.try_call(token, selector("symbol()"), block)
        meta["symbol"] = _decode_symbol(out) if out else None
    except RpcError:
        meta["symbol"] = None
    return meta


def _decode_symbol(out: str) -> str | None:
    raw = hex_to_bytes(out)
    try:
        (s,) = abi_decode(["string"], raw)
        return str(s)[:32]
    except Exception:  # bytes32 symbols (e.g. MKR)
        return raw[:32].rstrip(b"\x00").decode("utf-8", "replace")[:32] or None


def require_pool(pools: list[dict[str, Any]], pool_id: str | None) -> dict[str, Any]:
    if not pools:
        raise AppError("no_pool", "No pool using this hook was found; provide a pool ID.", status_code=422)
    if pool_id:
        for p in pools:
            if p["pool_id"].lower() == pool_id.lower():
                return p
        raise AppError("pool_not_found", f"Pool {pool_id} does not use this hook.", status_code=422)
    return pools[0]
