"""Celery worker entry point.

celery -A app.worker.celery_app worker -Q default --loglevel=INFO --concurrency=2   # scans, reports, AI
celery -A app.worker.celery_app worker -Q sim --loglevel=INFO --concurrency=1       # Foundry simulations
celery -A app.worker.celery_app beat                                                # periodic stale-job reaper
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings
from app.observability import configure_logging

_settings = get_settings()
configure_logging(_settings.log_level)

celery_app = Celery("hooklens", broker=_settings.redis_url or "redis://localhost:6379/0")
celery_app.conf.update(
    task_default_queue="default",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=_settings.simulation_timeout_s + 120,
    broker_connection_retry_on_startup=True,
    beat_schedule={"reap-stale-jobs": {"task": "hooklens.reap", "schedule": 60.0}},
)


@celery_app.task(name="hooklens.run_job")
def run_job(job_id: str) -> str:
    from app.jobs.manager import execute_job

    return execute_job(job_id)


@celery_app.task(name="hooklens.reap")
def reap() -> int:
    from app.jobs.manager import reap_stale_jobs

    return reap_stale_jobs()
