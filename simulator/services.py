"""Scenario ticks and lifecycle — BACKEND_FLOW.md §7.3.

The tick body is deliberately defensive. It runs on a scheduler thread with no
user watching, so an exception that escapes would kill the job silently and the
demo would simply stop with no indication why (PRD NFR-9).
"""

from __future__ import annotations

import logging

import pandas as pd
from django.utils import timezone

from core.constants import BatchSource, ScenarioStatus
from datasets.services import get_active_baseline
from monitoring.services import IngestionError, ingest_batch
from simulator import transforms
from simulator.models import SimulationScenario

logger = logging.getLogger("driftguard.scheduler")


def load_holdout(scenario) -> pd.DataFrame:
    """The pool of rows this scenario replays."""
    if not scenario.holdout_file:
        raise IngestionError(
            f"Scenario '{scenario.name}' has no holdout data to replay. "
            f"Upload a CSV of held-out rows first."
        )
    scenario.holdout_file.open("rb")
    try:
        return pd.read_csv(scenario.holdout_file)
    finally:
        scenario.holdout_file.close()


def tick(scenario_id: int):
    """Produce one batch and run it through the monitoring pipeline.

    Reloads the scenario from the database rather than trusting a closure: the
    job outlives any single request, and its interval, plan or status may have
    been edited since it was scheduled.
    """
    try:
        scenario = SimulationScenario.objects.select_related("ml_model").get(
            pk=scenario_id
        )
    except SimulationScenario.DoesNotExist:
        logger.info("scenario %s no longer exists; unscheduling", scenario_id)
        from simulator.scheduler import unschedule

        unschedule(scenario_id)
        return None

    if scenario.status != ScenarioStatus.RUNNING:
        return None

    try:
        run = run_one_batch(scenario)
    except Exception as exc:  # noqa: BLE001 — must never reach the scheduler thread
        logger.exception("scenario %s tick failed", scenario_id)
        scenario.last_error = str(exc)[:1000]
        scenario.last_tick_at = timezone.now()
        scenario.save(update_fields=["last_error", "last_tick_at"])
        return None

    return run


def run_one_batch(scenario, advance: bool = True):
    """Build and ingest a single batch. Also serves the "Run check now" button.

    ``next_batch_index`` advances even when the pipeline skips the batch because
    another run was already in progress — otherwise a busy model would replay
    the same phase forever and never reach the drifted ones.
    """
    baseline = get_active_baseline(scenario.ml_model)
    if baseline is None:
        raise IngestionError(
            f"'{scenario.ml_model.name}' has no baseline dataset, so there is "
            f"nothing to compare a simulated batch against."
        )

    holdout = load_holdout(scenario)
    index = scenario.next_batch_index

    batch = transforms.build_batch(
        holdout,
        baseline.profile,
        scenario.drift_plan,
        index,
        scenario.batch_size,
        include_labels=scenario.include_labels,
        target_column=scenario.ml_model.target_column,
    )

    run = ingest_batch(
        scenario.ml_model,
        batch,
        source=BatchSource.SIMULATOR,
        batch_index=index,
    )

    if advance:
        scenario.next_batch_index = index + 1
    scenario.last_tick_at = timezone.now()
    scenario.last_error = ""
    scenario.save(update_fields=["next_batch_index", "last_tick_at", "last_error"])

    logger.info(
        "scenario %s batch %s -> run %s",
        scenario.pk,
        index,
        run.pk if run else "skipped (model busy)",
    )
    return run


# ──────────────────────────────────────────────────────────────────────
# Lifecycle
# ──────────────────────────────────────────────────────────────────────


def start(scenario):
    from simulator.scheduler import schedule

    scenario.status = ScenarioStatus.RUNNING
    scenario.last_error = ""
    scenario.save(update_fields=["status", "last_error"])
    schedule(scenario)
    return scenario


def pause(scenario):
    """Stop ticking but keep the position, so resuming continues the story."""
    from simulator.scheduler import unschedule

    scenario.status = ScenarioStatus.PAUSED
    scenario.save(update_fields=["status"])
    unschedule(scenario.pk)
    return scenario


def stop(scenario, reset=False):
    from simulator.scheduler import unschedule

    scenario.status = ScenarioStatus.STOPPED
    if reset:
        scenario.next_batch_index = 0
    scenario.save(update_fields=["status", "next_batch_index"])
    unschedule(scenario.pk)
    return scenario


def resume_running_scenarios():
    """Re-schedule everything that was running when the process last stopped.

    Called once at startup. Without it a restart leaves scenarios marked RUNNING
    in the database with no job behind them — the screen would claim they are
    running while nothing ticks.
    """
    from simulator.scheduler import schedule

    scenarios = SimulationScenario.objects.filter(status=ScenarioStatus.RUNNING)
    for scenario in scenarios:
        schedule(scenario)
    if scenarios:
        logger.info("resumed %s running scenario(s)", len(scenarios))
    return list(scenarios)
