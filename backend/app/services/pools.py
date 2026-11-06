"""Uniswap v4 pool discovery and on-chain pool state.

Pools are discovered from PoolManager `Initialize` events (the hook address is not an indexed
topic, so logs are filtered client-side) in chunked block ranges. Pool state is read through
`extsload` using the StateLibrary storage layout of the pinned v4-core version.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "from_block": self.from_block,
            "to_block": self.to_block,
            "scanned_to": self.scanned_to,
            "reason": self.reason,
            "pool_count": len(self.pools),
        }


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
    hook: str,
    to_block: int,
    *,
    pool_id: str | None = None,
    should_stop: Any = None,
) -> DiscoveryResult:
    if not chain.pool_manager:
        return DiscoveryResult(status="failed", reason="No PoolManager is configured for this chain.")
    s = get_settings()
    start = chain.pool_manager_deploy_block
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
                res.status, res.reason = "partial", "RPC endpoint refuses even small log ranges."
                return res
            chunk //= 4
            continue
        except RpcError as e:
            res.status = "partial" if res.pools else "failed"
            res.reason = e.message
            return res
        for entry in logs:
            try:
                p = _parse_initialize(entry)
            except (ValueError, KeyError, IndexError):
                continue
            if p.hooks.lower() == hook.lower():
                res.pools.append(p)
        res.scanned_to = end
        cur = end + 1
        chunks += 1
        if pool_id and res.pools:
            break
    return res


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
