"""Live Uniswap v4 pool state, read from the chain at its latest block.

This is the only place that reads *current* pool state. Everything it returns carries provenance:
chain, PoolManager, block number, block hash, block timestamp and the time it was fetched.

Reads go through the PoolManager's `extsload` with the StateLibrary layout (see `pools.read_pool_state`),
pinned to one block so price, tick and liquidity are consistent with each other.

Caching:
  * The chain head (latest block) is cached for `live_head_ttl_s` so a burst of requests shares one
    `eth_getBlockByNumber("latest")`.
  * Pool state is cached by (chain, PoolManager, pool, block). A new head block means a new key, so a
    cache hit can never serve state from an older block than the head that was just observed.
  * Identical in-flight reads are deduplicated (single flight).

Failures are never papered over: if the chain cannot be read, `LiveStateUnavailable` is raised.
There is no fallback to scan snapshots here.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from eth_abi import encode as abi_encode

from app.chains import ChainConfig
from app.config import get_settings
from app.errors import AppError, RpcError, RpcNotConfigured
from app.services.evm import keccak
from app.services.pools import read_pool_state
from app.services.rpc import RpcClient

T = TypeVar("T")


class LiveStateUnavailable(AppError):
    """Live chain data could not be read. Callers must not substitute older data."""

    def __init__(self, message: str, *, cause: str, chain_id: int, retryable: bool = True) -> None:
        super().__init__(
            "live_state_unavailable",
            message,
            status_code=503,
            details={"cause": cause, "chain_id": chain_id},
            retryable=retryable,
        )


@dataclass(frozen=True)
class BlockRef:
    number: int
    hash: str | None
    timestamp: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_number": self.number,
            "block_hash": self.hash,
            "block_timestamp": self.timestamp,
            "block_time": (
                datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat() if self.timestamp is not None else None
            ),
        }


def compute_pool_id(currency0: str, currency1: str, fee: int, tick_spacing: int, hooks: str) -> str:
    """PoolId = keccak256(abi.encode(PoolKey)), as in v4-core PoolIdLibrary."""
    enc = abi_encode(
        ["address", "address", "uint24", "int24", "address"],
        [currency0, currency1, int(fee), int(tick_spacing), hooks],
    )
    return "0x" + keccak(enc).hex()


def validate_pool_identity(pool: dict[str, Any], *, hook: str | None = None) -> str:
    """Check that the stored PoolKey hashes to the pool ID (and uses `hook`). Returns the pool ID."""
    try:
        pid = str(pool["pool_id"]).lower()
        key = (pool["currency0"], pool["currency1"], int(pool["fee"]), int(pool["tick_spacing"]), pool["hooks"])
    except (KeyError, TypeError, ValueError) as e:
        raise AppError("pool_key_incomplete", "The pool's key is incomplete; re-scan the hook.", status_code=422) from e
    if compute_pool_id(*key) != pid:
        raise AppError(
            "pool_identity_mismatch",
            "The pool ID does not match its PoolKey (currency0, currency1, fee, tickSpacing, hooks).",
            status_code=422,
        )
    if hook and str(pool["hooks"]).lower() != hook.lower():
        raise AppError("pool_hook_mismatch", "This pool does not use the scanned hook.", status_code=422)
    return pid


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class LivePoolService:
    def __init__(self, rpc_factory: Callable[[ChainConfig], RpcClient] | None = None) -> None:
        s = get_settings()
        self._factory = rpc_factory or (lambda chain: RpcClient(chain, timeout=s.live_rpc_timeout_s))
        self._head_ttl = s.live_head_ttl_s
        self._max = max(8, s.live_state_cache_size)
        self._lock = threading.Lock()
        self._heads: dict[int, tuple[BlockRef, float, str]] = {}
        self._verified_chains: set[int] = set()
        self._states: OrderedDict[tuple[Any, ...], tuple[dict[str, Any], str]] = OrderedDict()
        self._inflight: dict[tuple[Any, ...], Future[Any]] = {}

    # ------------------------------------------------------------------ plumbing
    def _single_flight(self, key: tuple[Any, ...], fn: Callable[[], T]) -> T:
        with self._lock:
            fut = self._inflight.get(key)
            owner = fut is None
            if fut is None:
                fut = Future()
                self._inflight[key] = fut
        if not owner:
            return fut.result()
        try:
            value = fn()
        except BaseException as e:
            fut.set_exception(e)
            raise
        else:
            fut.set_result(value)
            return value
        finally:
            with self._lock:
                self._inflight.pop(key, None)

    def _rpc(self, chain: ChainConfig) -> RpcClient:
        try:
            return self._factory(chain)
        except RpcNotConfigured as e:
            raise LiveStateUnavailable(
                f"No RPC endpoint is configured for {chain.name}, so live data cannot be read.",
                cause="rpc_not_configured",
                chain_id=chain.chain_id,
                retryable=False,
            ) from e

    @staticmethod
    def _wrap(chain: ChainConfig, e: RpcError) -> LiveStateUnavailable:
        return LiveStateUnavailable(
            f"Live data could not be read from {chain.name}: {e.message}",
            cause=e.code,
            chain_id=chain.chain_id,
            retryable=e.retryable,
        )

    def clear(self) -> None:
        with self._lock:
            self._heads.clear()
            self._states.clear()
            self._verified_chains.clear()

    # ------------------------------------------------------------------ head
    def head(self, chain: ChainConfig, *, force: bool = False) -> tuple[BlockRef, str, bool]:
        """(latest block, fetched_at ISO, from_cache)."""
        with self._lock:
            cached = self._heads.get(chain.chain_id)
        if cached and not force and time.monotonic() - cached[1] < self._head_ttl:
            return cached[0], cached[2], True

        def fetch() -> tuple[BlockRef, str, bool]:
            with self._rpc(chain) as rpc:
                try:
                    if chain.chain_id not in self._verified_chains:
                        actual = rpc.chain_id()
                        if actual != chain.chain_id:
                            raise LiveStateUnavailable(
                                f"The RPC endpoint for {chain.name} reports chain {actual}, not {chain.chain_id}.",
                                cause="chain_id_mismatch",
                                chain_id=chain.chain_id,
                                retryable=False,
                            )
                        with self._lock:
                            self._verified_chains.add(chain.chain_id)
                    blk = rpc.get_block("latest")
                except RpcError as e:
                    raise self._wrap(chain, e) from e
            if not blk or blk.get("number") is None:
                raise LiveStateUnavailable(
                    f"{chain.name} returned no latest block.", cause="no_block", chain_id=chain.chain_id
                )
            ref = BlockRef(
                number=int(blk["number"], 16),
                hash=blk.get("hash"),
                timestamp=int(blk["timestamp"], 16) if blk.get("timestamp") else None,
            )
            fetched = _now_iso()
            with self._lock:
                self._heads[chain.chain_id] = (ref, time.monotonic(), fetched)
            return ref, fetched, False

        return self._single_flight(("head", chain.chain_id), fetch)

    # ------------------------------------------------------------------ pool state
    def pool_state(
        self, chain: ChainConfig, pool: dict[str, Any], *, hook: str | None = None, force: bool = False
    ) -> dict[str, Any]:
        """Current state of `pool` (a scan pool record with its PoolKey) with full provenance."""
        if not chain.pool_manager:
            raise AppError("pool_manager_unknown", f"No PoolManager is configured for {chain.name}.", status_code=422)
        pool_id = validate_pool_identity(pool, hook=hook)
        ref, head_fetched_at, head_cached = self.head(chain, force=force)
        key = (chain.chain_id, chain.pool_manager.lower(), pool_id, ref.number)

        with self._lock:
            hit = self._states.get(key)
            if hit is not None:
                self._states.move_to_end(key)
        if hit is not None:
            state, fetched_at = hit
            cache_hit = True
        else:

            def fetch() -> tuple[dict[str, Any], str]:
                with self._rpc(chain) as rpc:
                    try:
                        st = read_pool_state(rpc, chain.pool_manager or "", pool_id, ref.number)
                    except RpcError as e:
                        raise self._wrap(chain, e) from e
                when = _now_iso()
                with self._lock:
                    self._states[key] = (st, when)
                    while len(self._states) > self._max:
                        self._states.popitem(last=False)
                return st, when

            state, fetched_at = self._single_flight(("state", *key), fetch)
            cache_hit = False

        if not state.get("initialized"):
            raise AppError(
                "pool_not_initialized",
                f"Pool {pool_id} is not initialized on the {chain.name} PoolManager at block {ref.number}.",
                status_code=404,
                details={"block_number": ref.number},
            )
        return {
            "source": "live",
            "chain_id": chain.chain_id,
            "chain_name": chain.name,
            "pool_manager": chain.pool_manager,
            "pool_id": pool_id,
            **ref.to_dict(),
            "fetched_at": fetched_at,
            "head_fetched_at": head_fetched_at,
            "cache": {"state_hit": cache_hit, "head_hit": head_cached, "head_ttl_s": self._head_ttl},
            "state": {k: state[k] for k in ("sqrt_price_x96", "tick", "liquidity", "lp_fee", "protocol_fee")}
            | {"initialized": True, "block_number": ref.number},
        }


_service: LivePoolService | None = None
_service_lock = threading.Lock()


def get_live_pool_service() -> LivePoolService:
    global _service
    with _service_lock:
        if _service is None:
            _service = LivePoolService()
        return _service


def set_live_pool_service(svc: LivePoolService | None) -> None:
    """Testing hook: install a service with a custom RPC factory (or reset with None)."""
    global _service
    with _service_lock:
        _service = svc


__all__ = [
    "BlockRef",
    "LivePoolService",
    "LiveStateUnavailable",
    "compute_pool_id",
    "get_live_pool_service",
    "set_live_pool_service",
    "validate_pool_identity",
]
