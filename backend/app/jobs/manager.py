"""Persistent job lifecycle.

State machine:  queued -> running -> succeeded | failed | cancelled | timed_out
                running -> queued (retry, only for retryable infrastructure errors)

The `jobs` row is the source of truth for status, stage, progress and events, so a browser
refresh, an API restart or a different API replica always sees the same state. Workers send
heartbeats; the reaper marks jobs whose worker vanished as failed (`worker_lost`).
"""

from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.base import session_scope
from app.db.models import Job, utcnow
from app.errors import AppError, Cancelled, JobTimeout

log = logging.getLogger(__name__)

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}
MAX_EVENTS = 300
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

Handler = Callable[["JobContext", dict[str, Any]], dict[str, Any] | None]
_HANDLERS: dict[str, Handler] = {}


def register(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return deco


def handlers() -> dict[str, Handler]:
    # Import handler modules lazily so registration happens in API and worker processes alike.
    from app.services import ai_service, report_service, scan_service, simulation_service  # noqa: F401

    return _HANDLERS


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def create_job(
    db: Session,
    *,
    kind: str,
    workspace_id: str,
    subject_id: str | None,
    payload: dict[str, Any],
    timeout_s: int,
    max_attempts: int = 2,
) -> Job:
    job = Job(
        kind=kind,
        workspace_id=workspace_id,
        subject_id=subject_id,
        payload=payload,
        timeout_s=timeout_s,
        max_attempts=max_attempts,
        status="queued",
        stage="queued",
        events=[
            {"ts": utcnow().isoformat(), "stage": "queued", "progress": 0.0, "message": "Job queued", "level": "info"}
        ],
    )
    db.add(job)
    db.flush()
    return job


class JobContext:
    """Handle passed to job handlers for progress, heartbeats, cancellation and deadlines."""

    def __init__(self, job_id: str, timeout_s: int) -> None:
        self.job_id = job_id
        self.deadline = time.monotonic() + timeout_s
        self._last_cancel_check = 0.0
        self._cancelled = False

    def update(
        self, stage: str, progress: float, message: str, level: str = "info", data: dict[str, Any] | None = None
    ) -> None:
        with session_scope() as db:
            job = db.get(Job, self.job_id)
            if job is None:
                return
            job.stage = stage
            job.progress = max(0.0, min(1.0, progress))
            job.heartbeat_at = utcnow()
            ev = {
                "ts": utcnow().isoformat(),
                "stage": stage,
                "progress": job.progress,
                "message": message,
                "level": level,
            }
            if data:
                ev["data"] = data
            job.events = (list(job.events or []) + [ev])[-MAX_EVENTS:]
            if job.cancel_requested:
                self._cancelled = True
        self.check()

    def heartbeat(self) -> None:
        with session_scope() as db:
            job = db.get(Job, self.job_id)
            if job is not None:
                job.heartbeat_at = utcnow()
                self._cancelled = self._cancelled or bool(job.cancel_requested)

    def cancel_requested(self) -> bool:
        now = time.monotonic()
        if not self._cancelled and now - self._last_cancel_check > 0.5:
            self._last_cancel_check = now
            with session_scope() as db:
                job = db.get(Job, self.job_id)
                self._cancelled = bool(job and job.cancel_requested)
        return self._cancelled

    def time_left(self) -> float:
        return self.deadline - time.monotonic()

    def check(self) -> None:
        """Raise Cancelled / JobTimeout at safe points."""
        if self.cancel_requested():
            raise Cancelled()
        if self.time_left() <= 0:
            raise JobTimeout()


def _finish(job_id: str, status: str, *, error: dict[str, Any] | None = None, message: str = "") -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = status
        job.finished_at = utcnow()
        job.error = error
        if status == "succeeded":
            job.progress = 1.0
            job.stage = "done"
        ev = {
            "ts": utcnow().isoformat(),
            "stage": job.stage,
            "progress": job.progress,
            "message": message or status,
            "level": "error" if error else "info",
        }
        job.events = (list(job.events or []) + [ev])[-MAX_EVENTS:]


def execute_job(job_id: str) -> str:
    """Run one job to a terminal (or re-queued) state. Safe to call from threads or Celery."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            log.warning("job vanished", extra={"job_id": job_id})
            return "missing"
        if job.status in TERMINAL:
            return job.status
        if job.cancel_requested:
            job.status, job.finished_at = "cancelled", utcnow()
            return "cancelled"
        job.status = "running"
        job.attempts += 1
        job.started_at = job.started_at or utcnow()
        job.heartbeat_at = utcnow()
        job.worker = WORKER_ID
        kind, payload, timeout_s = job.kind, dict(job.payload or {}), job.timeout_s
        attempts, max_attempts = job.attempts, job.max_attempts

    handler = handlers().get(kind)
    if handler is None:
        _finish(job_id, "failed", error={"code": "unknown_job_kind", "message": f"No handler for job kind {kind}."})
        return "failed"

    ctx = JobContext(job_id, timeout_s)
    try:
        result = handler(ctx, payload) or {}
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.payload = {**(job.payload or {}), "result": result}
        _finish(job_id, "succeeded", message=result.get("message", "Completed"))
        return "succeeded"
    except Cancelled:
        _on_terminal_hook(kind, payload, "cancelled", None)
        _finish(job_id, "cancelled", message="Cancelled by user")
        return "cancelled"
    except JobTimeout:
        err = {"code": "job_timeout", "message": f"The job exceeded its {timeout_s}s time limit."}
        _on_terminal_hook(kind, payload, "timed_out", err)
        _finish(job_id, "timed_out", error=err, message=err["message"])
        return "timed_out"
    except AppError as e:
        if e.retryable and attempts < max_attempts:
            with session_scope() as db:
                job = db.get(Job, job_id)
                if job is not None:
                    job.status = "queued"
                    ev = {
                        "ts": utcnow().isoformat(),
                        "stage": "retry",
                        "progress": job.progress,
                        "message": f"Retrying after transient error: {e.message}",
                        "level": "warning",
                    }
                    job.events = (list(job.events or []) + [ev])[-MAX_EVENTS:]
            time.sleep(min(5.0, 1.5 * attempts))
            from app.jobs.dispatch import get_dispatcher

            get_dispatcher().dispatch(job_id)
            return "queued"
        _on_terminal_hook(kind, payload, "failed", e.to_dict())
        _finish(job_id, "failed", error=e.to_dict(), message=e.message)
        return "failed"
    except Exception:
        log.exception("job crashed", extra={"job_id": job_id, "kind": kind})
        err = {"code": "internal_error", "message": "The job failed because of an internal error. It has been logged."}
        _on_terminal_hook(kind, payload, "failed", err)
        _finish(job_id, "failed", error=err, message=err["message"])
        return "failed"


_TERMINAL_HOOKS: dict[str, Callable[[dict[str, Any], str, dict[str, Any] | None], None]] = {}


def on_terminal(kind: str) -> Callable[[Any], Any]:
    """Register a callback that marks the job's subject (scan/simulation) when the job ends badly."""

    def deco(fn: Any) -> Any:
        _TERMINAL_HOOKS[kind] = fn
        return fn

    return deco


def _on_terminal_hook(kind: str, payload: dict[str, Any], status: str, error: dict[str, Any] | None) -> None:
    hook = _TERMINAL_HOOKS.get(kind)
    if hook:
        try:
            hook(payload, status, error)
        except Exception:
            log.exception("terminal hook failed", extra={"kind": kind})


def request_cancel(db: Session, job: Job) -> Job:
    if job.status in TERMINAL:
        return job
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = utcnow()
        _on_terminal_hook(job.kind, dict(job.payload or {}), "cancelled", None)
    ev = {
        "ts": utcnow().isoformat(),
        "stage": job.stage,
        "progress": job.progress,
        "message": "Cancellation requested",
        "level": "warning",
    }
    job.events = (list(job.events or []) + [ev])[-MAX_EVENTS:]
    return job


def reap_stale_jobs() -> int:
    """Mark running jobs whose heartbeat is older than the threshold as failed (worker lost)."""
    s = get_settings()
    cutoff = utcnow() - timedelta(seconds=s.job_heartbeat_timeout_s)
    n = 0
    with session_scope() as db:
        rows = db.execute(select(Job).where(Job.status == "running")).scalars().all()
        for job in rows:
            hb = _aware(job.heartbeat_at) or _aware(job.started_at)
            if hb is not None and hb < cutoff:
                job.status = "failed"
                job.finished_at = utcnow()
                job.error = {
                    "code": "worker_lost",
                    "message": "The worker processing this job stopped responding. Partial results are kept; retry the job.",
                }
                _on_terminal_hook(job.kind, dict(job.payload or {}), "failed", job.error)
                n += 1
    return n
