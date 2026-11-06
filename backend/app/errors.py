"""Typed application errors.

Every error that can reach a user has a stable machine-readable code, a safe human message,
an HTTP status, and optional structured details. Internal exception text is never exposed.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base error with a stable code and a user-safe message."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }


class NotFound(AppError):
    def __init__(self, what: str, ident: str) -> None:
        super().__init__("not_found", f"{what} '{ident}' was not found.", status_code=404)


class RpcError(AppError):
    def __init__(self, code: str, message: str, *, retryable: bool = False, details: dict[str, Any] | None = None):
        super().__init__(code, message, status_code=502, details=details, retryable=retryable)


class RpcNotConfigured(AppError):
    def __init__(self, chain_id: int) -> None:
        super().__init__(
            "rpc_not_configured",
            f"No RPC endpoint is configured for chain {chain_id}. An operator must set it in the server "
            "environment (e.g. HOOKLENS_MAINNET_RPC_URL).",
            status_code=503,
        )


class RpcUnavailable(RpcError):
    def __init__(self, message: str = "The chain RPC endpoint is unreachable or timed out.") -> None:
        super().__init__("rpc_unavailable", message, retryable=True)


class RpcRateLimited(RpcError):
    def __init__(self) -> None:
        super().__init__("rpc_rate_limited", "The chain RPC endpoint is rate limiting requests.", retryable=True)


class ArchiveStateUnavailable(RpcError):
    def __init__(self, block: int | str) -> None:
        super().__init__(
            "archive_state_unavailable",
            f"The RPC endpoint cannot serve historical state at block {block}. An archive node is required.",
        )


class ExplorerError(AppError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__("explorer_unavailable", message, status_code=502, retryable=retryable)


class Cancelled(Exception):
    """Raised inside a job when cancellation has been requested."""


class JobTimeout(Exception):
    """Raised inside a job when its deadline has passed."""
