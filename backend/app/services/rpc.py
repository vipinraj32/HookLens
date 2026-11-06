"""JSON-RPC client with bounded retries and precise error classification."""

from __future__ import annotations

import itertools
import logging
import time
from typing import Any

import httpx

from app.chains import ChainConfig
from app.config import get_settings
from app.errors import (
    ArchiveStateUnavailable,
    RpcError,
    RpcNotConfigured,
    RpcRateLimited,
    RpcUnavailable,
)

log = logging.getLogger(__name__)

_ARCHIVE_MARKERS = (
    "missing trie node",
    "header not found",
    "historical state",
    "state is not available",
    "state not available",
    "pruned",
    "archive",
    "block not found",
)
_RANGE_MARKERS = ("query returned more than", "block range", "too many results", "limit exceeded", "range is too large")


class LogRangeTooLarge(RpcError):
    def __init__(self) -> None:
        super().__init__("log_range_too_large", "The RPC endpoint rejected the log query range.", retryable=True)


class RpcClient:
    """Thin synchronous JSON-RPC client bound to one configured chain."""

    _ids = itertools.count(1)

    def __init__(
        self, chain: ChainConfig, *, timeout: float | None = None, transport: httpx.BaseTransport | None = None
    ):
        if not chain.rpc_url:
            raise RpcNotConfigured(chain.chain_id)
        s = get_settings()
        self.chain = chain
        self._url = chain.rpc_url
        self._retries = s.rpc_max_retries
        self._client = httpx.Client(timeout=timeout or s.rpc_timeout_s, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RpcClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ core
    def call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        delay = 0.5
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = self._client.post(self._url, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = RpcUnavailable()
                log.warning(
                    "rpc transport error", extra={"method": method, "attempt": attempt, "err": type(e).__name__}
                )
            else:
                if resp.status_code == 429:
                    last = RpcRateLimited()
                elif resp.status_code >= 500:
                    last = RpcUnavailable(f"The chain RPC endpoint returned HTTP {resp.status_code}.")
                elif resp.status_code >= 400:
                    raise RpcError("rpc_http_error", f"The chain RPC endpoint returned HTTP {resp.status_code}.")
                else:
                    try:
                        body = resp.json()
                    except ValueError as e:
                        raise RpcError("rpc_bad_response", "The chain RPC endpoint returned invalid JSON.") from e
                    if "error" in body and body["error"]:
                        self._raise_rpc_error(body["error"], params)
                    return body.get("result")
            if attempt < self._retries:
                time.sleep(delay)
                delay *= 2
        assert last is not None
        raise last

    def _raise_rpc_error(self, err: dict[str, Any], params: list[Any]) -> None:
        msg = str(err.get("message", "")).lower()
        code = err.get("code")
        if code == -32005 or "rate limit" in msg or "too many requests" in msg:
            raise RpcRateLimited()
        if any(m in msg for m in _RANGE_MARKERS):
            raise LogRangeTooLarge()
        if any(m in msg for m in _ARCHIVE_MARKERS):
            block = params[-1] if params else "unknown"
            raise ArchiveStateUnavailable(block if isinstance(block, (int, str)) else "unknown")
        if "execution reverted" in msg or code == 3:
            raise RpcError("call_reverted", "eth_call reverted.", details={"data": err.get("data")})
        raise RpcError("rpc_error", "The chain RPC endpoint returned an error.", details={"rpc_code": code})

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _block(block: int | str) -> str:
        return hex(block) if isinstance(block, int) else block

    def chain_id(self) -> int:
        return int(self.call("eth_chainId", []), 16)

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def get_block(self, block: int | str) -> dict[str, Any] | None:
        res = self.call("eth_getBlockByNumber", [self._block(block), False])
        return res if isinstance(res, dict) else None

    def get_code(self, address: str, block: int | str = "latest") -> str:
        return str(self.call("eth_getCode", [address, self._block(block)]) or "0x")

    def get_storage_at(self, address: str, slot: int | str, block: int | str = "latest") -> str:
        s = hex(slot) if isinstance(slot, int) else slot
        return str(self.call("eth_getStorageAt", [address, s, self._block(block)]))

    def eth_call(self, to: str, data: str, block: int | str = "latest") -> str:
        return str(self.call("eth_call", [{"to": to, "data": data}, self._block(block)]))

    def try_call(self, to: str, data: str, block: int | str = "latest") -> str | None:
        """eth_call that returns None on revert instead of raising."""
        try:
            out = self.eth_call(to, data, block)
        except RpcError as e:
            if e.code == "call_reverted":
                return None
            raise
        return out if out and out != "0x" else None

    def get_logs(self, address: str, topics: list[Any], from_block: int, to_block: int) -> list[dict[str, Any]]:
        res = self.call(
            "eth_getLogs",
            [{"address": address, "topics": topics, "fromBlock": hex(from_block), "toBlock": hex(to_block)}],
        )
        return list(res or [])
