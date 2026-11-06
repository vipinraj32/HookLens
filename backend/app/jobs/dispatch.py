"""Job dispatchers: in-process thread pool (dev/tests) or Celery (Docker/production)."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Protocol

from app.config import get_settings

log = logging.getLogger(__name__)


class Dispatcher(Protocol):
    name: str

    def dispatch(self, job_id: str) -> None: ...

    def health(self) -> dict[str, Any]: ...


class LocalDispatcher:
    name = "local"

    def __init__(self, workers: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hooklens-job")
        self._workers = workers
        self._inflight: dict[str, Future[Any]] = {}
        self._lock = threading.Lock()

    def dispatch(self, job_id: str) -> None:
        from app.jobs.manager import execute_job

        fut = self._pool.submit(execute_job, job_id)
        with self._lock:
            self._inflight[job_id] = fut
        fut.add_done_callback(lambda _f: self._done(job_id))

    def _done(self, job_id: str) -> None:
        with self._lock:
            self._inflight.pop(job_id, None)

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        """Test helper: block until the in-flight job finishes."""
        with self._lock:
            fut = self._inflight.get(job_id)
        if fut is not None:
            fut.result(timeout=timeout)

    def health(self) -> dict[str, Any]:
        with self._lock:
            inflight = len(self._inflight)
        return {"backend": "local", "ok": True, "workers": self._workers, "inflight": inflight}


# Simulations execute Foundry against user-chosen contracts, so they go to a separate queue
# consumed only by the hardened sim-worker container; everything else uses the default queue.
SIM_QUEUE = "sim"
DEFAULT_QUEUE = "default"


def queue_for(kind: str | None) -> str:
    return SIM_QUEUE if kind == "simulation" else DEFAULT_QUEUE


class CeleryDispatcher:
    name = "celery"

    def dispatch(self, job_id: str) -> None:
        from app.db.base import session_scope
        from app.db.models import Job
        from app.worker import celery_app

        with session_scope() as db:
            job = db.get(Job, job_id)
            kind = job.kind if job is not None else None
        celery_app.send_task("hooklens.run_job", args=[job_id], queue=queue_for(kind))

    def health(self) -> dict[str, Any]:
        from app.worker import celery_app

        try:
            replies = celery_app.control.ping(timeout=1.0) or []
        except Exception as e:
            return {"backend": "celery", "ok": False, "workers": 0, "error": type(e).__name__}
        return {"backend": "celery", "ok": bool(replies), "workers": len(replies)}


_dispatcher: Dispatcher | None = None
_lock = threading.Lock()


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    with _lock:
        if _dispatcher is None:
            s = get_settings()
            _dispatcher = CeleryDispatcher() if s.job_backend == "celery" else LocalDispatcher(s.local_job_workers)
        return _dispatcher


def set_dispatcher(d: Dispatcher | None) -> None:
    global _dispatcher
    with _lock:
        _dispatcher = d
