"""APScheduler wiring — BACKEND_FLOW.md §7.

In-process on purpose: no Redis, no Celery, no broker to install on a demo
machine. The cost is that exactly one worker may run — two workers means two
schedulers means every batch delivered twice.
"""

from __future__ import annotations

import atexit
import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings

logger = logging.getLogger("driftguard.scheduler")

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def start_scheduler():
    """Start the background scheduler exactly once.

    Django's autoreloader runs AppConfig.ready() in **both** the reloader
    process and the child process. Without the RUN_MAIN guard every scenario
    ticks twice, every batch is delivered twice, and the cause is invisible
    because both look like normal runs.
    """
    global _scheduler

    if not getattr(settings, "SCHEDULER_ENABLED", True):
        logger.info("scheduler disabled by settings")
        return None

    if _scheduler is not None:
        return _scheduler

    if settings.DEBUG and os.environ.get("RUN_MAIN") != "true":
        # The reloader's parent process. The child will start the real one.
        return None

    _scheduler = BackgroundScheduler(timezone=str(settings.TIME_ZONE))
    _scheduler.start()
    atexit.register(shutdown_scheduler)

    _register_maintenance_jobs()

    from simulator.services import resume_running_scenarios

    resume_running_scenarios()

    logger.info("scheduler started")
    return _scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _register_maintenance_jobs():
    """Alert auto-resolution and file retention."""
    from alerts.services import sweep

    _scheduler.add_job(
        _guarded(sweep, "alert_cooldown_sweep"),
        trigger=IntervalTrigger(minutes=5),
        id="alert_cooldown_sweep",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _guarded(_retention_cleanup, "retention_cleanup"),
        trigger=CronTrigger(hour=3, minute=0),
        id="retention_cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def _guarded(function, label):
    """Wrap a job so an exception is logged rather than killing the job.

    An uncaught exception inside an APScheduler job removes it from future
    scheduling. The demo would stop with nothing on screen to explain why.
    """

    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:  # noqa: BLE001
            logger.exception("scheduled job %s failed", label)
            return None

    wrapper.__name__ = f"guarded_{label}"
    return wrapper


def _retention_cleanup():
    """Delete batch *files* past the retention window; keep every DB record.

    History must stay intact (FR-13.1) — only the raw uploads are reclaimed.
    """
    from datetime import timedelta

    from django.utils import timezone

    from datasets.models import DataBatch

    days = getattr(settings, "BATCH_FILE_RETENTION_DAYS", 30)
    cutoff = timezone.now() - timedelta(days=days)

    removed = 0
    for batch in DataBatch.objects.filter(received_at__lt=cutoff).exclude(file=""):
        batch.file.delete(save=True)
        removed += 1
    if removed:
        logger.info("retention: removed %s batch file(s)", removed)
    return removed


# ──────────────────────────────────────────────────────────────────────
# Scenario jobs
# ──────────────────────────────────────────────────────────────────────


def schedule(scenario):
    """Add or replace the interval job for one scenario."""
    scheduler = start_scheduler()
    if scheduler is None:
        return None

    from simulator.services import tick

    scheduler.add_job(
        _guarded(tick, scenario.job_id),
        trigger=IntervalTrigger(seconds=scenario.interval_seconds),
        id=scenario.job_id,
        args=[scenario.pk],
        replace_existing=True,
        # A tick arriving while the previous one is still running is dropped
        # rather than queued: batches would otherwise pile up behind a slow run
        # and all fire at once when it finishes.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    logger.info("scheduled %s every %ss", scenario.job_id, scenario.interval_seconds)
    return scheduler.get_job(scenario.job_id)


def unschedule(scenario_id: int):
    scheduler = get_scheduler()
    if scheduler is None:
        return
    job_id = f"scenario_tick_{scenario_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("unscheduled %s", job_id)


def next_run_time(scenario):
    scheduler = get_scheduler()
    if scheduler is None:
        return None
    job = scheduler.get_job(scenario.job_id)
    return job.next_run_time if job else None
