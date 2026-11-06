"""Anonymous workspaces and rate limiting.

A workspace is an opaque random ID signed with HMAC-SHA256 (server secret). It is issued as an
HttpOnly cookie for browsers and can be sent as `X-HookLens-Workspace` by API clients. It scopes
ownership of scans, simulations and reports; it is not an authentication system and grants no
access to anything outside its own records. Analysis never requires a wallet or an account.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict

from fastapi import Request, Response

from app.config import get_settings
from app.errors import AppError

COOKIE = "hl_ws"
HEADER = "X-HookLens-Workspace"


def _sign(ws_id: str) -> str:
    key = get_settings().workspace_secret.get_secret_value().encode()
    return hmac.new(key, ws_id.encode(), hashlib.sha256).hexdigest()[:32]


def issue_token() -> tuple[str, str]:
    ws_id = secrets.token_hex(16)
    return ws_id, f"{ws_id}.{_sign(ws_id)}"


def verify_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    ws_id, sig = token.split(".", 1)
    if len(ws_id) != 32 or not all(c in "0123456789abcdef" for c in ws_id):
        return None
    return ws_id if hmac.compare_digest(sig, _sign(ws_id)) else None


def workspace(request: Request, response: Response) -> str:
    """FastAPI dependency: the caller's workspace ID, issuing a new one if absent or invalid."""
    token = request.headers.get(HEADER) or request.cookies.get(COOKIE)
    ws = verify_token(token)
    if ws is None:
        if request.headers.get(HEADER):
            raise AppError("invalid_workspace", "The workspace token is invalid.", status_code=401)
        ws, token = issue_token()
        s = get_settings()
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="lax",
            secure=s.environment == "production",
            max_age=60 * 60 * 24 * 365,
            path="/",
        )
    response.headers[HEADER] = token or ""
    return ws


class RateLimiter:
    """Fixed-window per-client limiter (per process; use one API replica or a shared proxy limit)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str, int], int] = defaultdict(int)
        self._lock = threading.Lock()

    def check(self, client: str, bucket: str, limit: int, window_s: int = 60) -> None:
        now = int(time.time())
        win = now // window_s
        key = (client, bucket, win)
        with self._lock:
            self._hits[key] += 1
            count = self._hits[key]
            if len(self._hits) > 50_000:
                for k in [k for k in self._hits if k[2] < win]:
                    del self._hits[k]
        if count > limit:
            raise AppError(
                "rate_limited",
                "Too many requests. Please slow down.",
                status_code=429,
                details={"retry_after_s": window_s - now % window_s},
                retryable=True,
            )


limiter = RateLimiter()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_jobs(request: Request) -> None:
    limiter.check(client_key(request), "jobs", get_settings().rate_limit_jobs_per_minute)
