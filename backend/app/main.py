"""FastAPI application factory.

uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api import routes_core, routes_lp, routes_reports, routes_sim
from app.api.security import client_key, limiter
from app.config import get_settings
from app.errors import AppError
from app.observability import configure_logging, correlation_id

log = logging.getLogger("hooklens.api")
PROBLEM = "application/problem+json"


def _problem(
    status: int,
    code: str,
    detail: str,
    *,
    details: dict | None = None,
    retryable: bool = False,
    title: str | None = None,
) -> JSONResponse:
    body = {
        "type": f"urn:hooklens:error:{code}",  # RFC 9457 type URI, not a web page
        "title": title or code.replace("_", " ").capitalize(),
        "status": status,
        "code": code,
        "detail": detail,
        "details": details or {},
        "retryable": retryable,
        "correlation_id": correlation_id.get(),
    }
    headers = {"X-Correlation-ID": correlation_id.get()}
    if status == 429 and details and "retry_after_s" in details:
        headers["Retry-After"] = str(details["retry_after_s"])
    return JSONResponse(body, status_code=status, media_type=PROBLEM, headers=headers)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level)
    if s.auto_migrate:
        from app.db.migrate import upgrade_head

        upgrade_head()
    from app.jobs.manager import handlers, reap_stale_jobs

    handlers()  # register job kinds in this process
    reaped = reap_stale_jobs()
    if reaped:
        log.warning("marked stale jobs as failed on startup", extra={"count": reaped})
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="HookLens API",
        version=__version__,
        description="Uniswap v4 hook intelligence and LP exposure analysis. All analysis results carry their "
        "evidence and confidence basis; nothing here is an audit or a guarantee of safety.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-HookLens-Workspace", "X-Correlation-ID", "Last-Event-ID"],
        expose_headers=["X-HookLens-Workspace", "X-Correlation-ID", "Retry-After"],
    )

    @app.middleware("http")
    async def context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        cid = "".join(c for c in cid if c.isalnum() or c in "-_")[:64] or uuid.uuid4().hex
        token = correlation_id.set(cid)
        try:
            if request.url.path.startswith("/v1") and request.method != "OPTIONS":
                try:
                    limiter.check(client_key(request), "all", s.rate_limit_per_minute)
                except AppError as e:
                    return _problem(e.status_code, e.code, e.message, details=e.details, retryable=True)
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        finally:
            correlation_id.reset(token)

    @app.exception_handler(AppError)
    async def app_error(_r: Request, e: AppError) -> JSONResponse:
        if e.status_code >= 500:
            log.warning("app error", extra={"code": e.code, "status": e.status_code})
        return _problem(e.status_code, e.code, e.message, details=e.details, retryable=e.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_r: Request, e: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(x.get("loc", [])), "msg": x.get("msg"), "type": x.get("type")} for x in e.errors()]
        return _problem(422, "validation_error", "The request is invalid.", details={"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_r: Request, e: StarletteHTTPException) -> JSONResponse:
        return _problem(e.status_code, "http_error", str(e.detail))

    @app.exception_handler(Exception)
    async def unhandled(_r: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _problem(500, "internal_error", "An internal error occurred. It has been logged.")

    app.include_router(routes_core.router)
    app.include_router(routes_sim.router)
    app.include_router(routes_lp.router)
    app.include_router(routes_reports.router)
    return app


app = create_app()
