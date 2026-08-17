"""The monitoring pipeline's Django layer — BACKEND_FLOW.md §4.

``ingest_batch()`` is where every ingestion path converges: CSV upload, the
scheduled simulator, and the REST endpoint all end here. Adding a fourth way in
means adding a caller, never a second pipeline.

The transaction boundaries are deliberate and are the reason this file is
structured the way it is:

* the batch row is written **before** the work starts, so a crash mid-run still
  leaves an auditable record
* the engine runs **outside any transaction**, because it can take seconds and
  holding a write transaction that long blocks every other writer under SQLite
* the results are written in **one atomic block**, so no run ever exists with
  drift results but no health score
* alert evaluation gets **its own transaction**, so a bug in alerting can never
  roll back a monitoring run that completed correctly
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache

import joblib
import pandas as pd
from django.db import transaction
from django.utils import timezone

from core.constants import (
    BatchSource,
    BatchStatus,
    RunStatus,
    TriggerSource,
    VersionStatus,
)
from datasets.models import DataBatch
from datasets.services import get_active_baseline, load_reference_sample
from monitoring.engine import performance, pipeline, profiling
from monitoring.models import (
    DataQualityReport,
    FeatureDriftResult,
    MonitoringRun,
    PerformanceSnapshot,
)

logger = logging.getLogger("driftguard.pipeline")


class IngestionError(RuntimeError):
    """The batch could not be accepted. Carries a message for the user."""


# ──────────────────────────────────────────────────────────────────────
# Per-model lock — PRD FR-05.6
# ──────────────────────────────────────────────────────────────────────

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _model_lock(model_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(model_id, threading.Lock())


# ──────────────────────────────────────────────────────────────────────
# Artifact cache
# ──────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=4)
def _load_artifact(version_id: int, file_hash: str):
    """Deserialise a model artifact, cached on (version, hash).

    Loading is the slowest step in a run, so the simulator's second and later
    ticks skip it entirely. Keying on the hash as well as the id means a
    re-uploaded artifact never serves a stale object from cache.
    """
    from registry.models import ModelVersion

    version = ModelVersion.objects.get(pk=version_id)
    version.artifact.open("rb")
    try:
        return joblib.load(version.artifact)
    finally:
        version.artifact.close()


def clear_artifact_cache():
    _load_artifact.cache_clear()


# ──────────────────────────────────────────────────────────────────────
# Baseline prediction distribution — contract C2
# ──────────────────────────────────────────────────────────────────────


def compute_baseline_prediction_distribution(version):
    """Score the baseline with this version and store the resulting class mix.

    Called once, at version activation. It is the reference the health score's
    stability component measures against (PRD §8.2) — computing it per run would
    compare a batch against itself and always return "perfectly stable".
    """
    baseline = get_active_baseline(version.ml_model)
    if baseline is None:
        return None

    frame = load_reference_sample(baseline)
    features = [c for c in baseline.feature_names if c in frame.columns]
    if not features:
        return None

    model = _load_artifact(version.pk, version.file_hash or "")
    predictions = performance.score_batch(model, frame, features)
    distribution = performance.prediction_distribution(predictions)

    version.baseline_prediction_distribution = distribution["proportions"]
    version.save(update_fields=["baseline_prediction_distribution"])
    return distribution["proportions"]


# ──────────────────────────────────────────────────────────────────────
# Reference accuracy — PRD §8.1
# ──────────────────────────────────────────────────────────────────────


def reference_accuracy_for(version):
    """The version's recorded training accuracy, else its first labelled run.

    Returns ``None`` when neither exists. The health score treats that as "no
    reference established yet" and scores performance at 100 — the first run
    sets the reference rather than being judged against one that does not exist.
    """
    if version.training_accuracy is not None:
        return version.training_accuracy

    first = (
        PerformanceSnapshot.objects.filter(
            run__model_version=version, labels_available=True
        )
        .order_by("run__created_at")
        .values_list("accuracy", flat=True)
        .first()
    )
    return first


# ──────────────────────────────────────────────────────────────────────
# Schema validation — BACKEND_FLOW §4 step 4
# ──────────────────────────────────────────────────────────────────────


def validate_batch_schema(frame: pd.DataFrame, schema: dict) -> tuple[bool, str]:
    """Reject a batch missing any required feature column.

    Extra columns are fine and are ignored; a *missing* one means the model
    cannot be scored, so the batch is rejected rather than half-processed.
    """
    required = profiling.feature_columns(schema)
    missing = [c for c in required if c not in frame.columns]
    if missing:
        return False, (
            f"Batch is missing {len(missing)} required column(s): "
            f"{', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}"
        )
    return True, ""


# ──────────────────────────────────────────────────────────────────────
# The pipeline
# ──────────────────────────────────────────────────────────────────────


def ingest_batch(
    ml_model,
    frame: pd.DataFrame,
    source: str = BatchSource.UPLOAD,
    submitted_by=None,
    batch_index: int | None = None,
    file_obj=None,
    original_filename: str = "",
) -> MonitoringRun | None:
    """Run one monitoring cycle over ``frame``. The single convergence point.

    Returns the completed :class:`MonitoringRun`, or ``None`` if another run for
    this model was already in progress and the tick was skipped (FR-05.6).

    Raises :class:`IngestionError` for pre-flight failures — a deactivated
    model, no active version, no baseline. Those are refusals to start, not
    failed runs, so they produce no run record.
    """
    lock = _model_lock(ml_model.pk)
    if not lock.acquire(blocking=False):
        logger.info("run skipped, model %s already running", ml_model.pk)
        return None

    try:
        version, baseline, thresholds = _preflight(ml_model)

        batch = DataBatch.objects.create(
            ml_model=ml_model,
            model_version=version,
            source=source,
            file=file_obj,
            original_filename=original_filename[:255],
            row_count=len(frame),
            status=BatchStatus.VALIDATING,
            submitted_by=submitted_by,
            batch_index=batch_index,
        )

        ok, message = validate_batch_schema(frame, baseline.schema)
        if not ok:
            batch.status = BatchStatus.REJECTED
            batch.rejection_reason = message
            batch.save(update_fields=["status", "rejection_reason"])
            _raise_batch_rejected(ml_model, message)
            raise IngestionError(message)

        target = profiling.target_column(baseline.schema)
        has_labels = bool(
            target and target in frame.columns and frame[target].notna().any()
        )
        batch.has_labels = has_labels
        batch.status = BatchStatus.PROCESSING
        batch.save(update_fields=["has_labels", "status"])

        run = MonitoringRun.objects.create(
            ml_model=ml_model,
            model_version=version,
            data_batch=batch,
            trigger_source=_trigger_for(source),
            status=RunStatus.RUNNING,
            started_at=timezone.now(),
            thresholds_snapshot=thresholds,
            labels_available=has_labels,
        )

        try:
            result = _run_engine(
                run, ml_model, version, baseline, frame, thresholds, target
            )
        except Exception as exc:  # noqa: BLE001 — recorded, never propagated
            logger.exception("monitoring run %s failed", run.pk)
            run.status = RunStatus.FAILED
            run.error_message = str(exc)[:2000]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_message", "completed_at"])
            batch.status = BatchStatus.FAILED
            batch.save(update_fields=["status"])
            _raise_run_failed(ml_model, run, str(exc))
            return run

        _persist(run, batch, result)
        _evaluate_alerts(run)
        return run
    finally:
        lock.release()


def _preflight(ml_model):
    """Refuse to start rather than record a failed run (BACKEND_FLOW §4 step 1)."""
    if not ml_model.is_active:
        raise IngestionError(
            f"'{ml_model.name}' is deactivated and accepts no batches."
        )

    version = ml_model.versions.filter(status=VersionStatus.ACTIVE).first()
    if version is None:
        raise IngestionError(
            f"'{ml_model.name}' has no active version. Upload and activate one first."
        )

    baseline = get_active_baseline(ml_model)
    if baseline is None:
        raise IngestionError(f"'{ml_model.name}' has no baseline dataset.")

    from alerts.services import resolve_thresholds

    return version, baseline, resolve_thresholds(ml_model)


def _trigger_for(source):
    return {
        BatchSource.UPLOAD: TriggerSource.UPLOAD,
        BatchSource.SIMULATOR: TriggerSource.SCHEDULED,
        BatchSource.API: TriggerSource.API,
    }.get(source, TriggerSource.MANUAL)


def _run_engine(run, ml_model, version, baseline, frame, thresholds, target):
    """Call the pure-Python engine. No transaction is held here on purpose."""
    model = _load_artifact(version.pk, version.file_hash or "")
    reference = load_reference_sample(baseline)

    classes = None
    if version.baseline_prediction_distribution:
        classes = sorted(version.baseline_prediction_distribution.keys())

    return pipeline.run_monitoring(
        frame,
        baseline.profile,
        reference,
        baseline.schema,
        model,
        thresholds=thresholds,
        baseline_prediction_distribution=version.baseline_prediction_distribution,
        reference_accuracy=reference_accuracy_for(version),
        target_column=target,
        class_labels=classes,
        positive_class=ml_model.positive_class or None,
    )


@transaction.atomic
def _persist(run, batch, result):
    """Write the whole result, or none of it (BACKEND_FLOW §4 step 8)."""
    drift = result["drift"]
    health = result["health"]
    quality = result["quality"]
    perf = result["performance"]

    run.overall_drift_status = drift["overall_status"]
    run.features_total = drift["counts"]["total"]
    run.features_high = drift["counts"]["high"]
    run.features_moderate = drift["counts"]["moderate"]
    run.features_insufficient = drift["counts"]["insufficient"]

    run.health_score = health["score"]
    run.health_raw_score = health.get("raw_score")
    run.health_capped = health.get("capped", False)
    run.health_band = health["band"]
    run.health_components = {
        "components": health["components"],
        "weights": health["weights"],
        "weighting": health["weighting"],
    }
    run.labels_available = perf["labels_available"]
    run.duration_ms = result["meta"]["duration_ms"]
    run.completed_at = timezone.now()
    run.status = RunStatus.COMPLETED
    run.save()

    FeatureDriftResult.objects.bulk_create(
        [
            FeatureDriftResult(
                run=run,
                feature_name=f["feature_name"],
                feature_type=f["feature_type"],
                test_name=f["test_name"] or "",
                test_statistic=f["test_statistic"],
                p_value=f["p_value"],
                psi=f["psi"],
                jsd=f["jsd"],
                status=f["status"],
                explanation=f.get("explanation", ""),
                baseline_summary=f.get("baseline_summary") or {},
                current_summary=f.get("current_summary") or {},
                unseen_categories=f.get("unseen_categories") or [],
            )
            for f in drift["features"]
        ]
    )

    DataQualityReport.objects.create(
        run=run,
        row_count=quality["row_count"],
        columns_checked=quality["columns_checked"],
        missing_total=quality["missing_total"],
        missing_pct=quality["missing_pct"],
        duplicate_rows=quality["duplicate_rows"],
        duplicate_pct=quality["duplicate_pct"],
        outlier_pct=quality["outlier_pct"],
        type_mismatch_columns=quality["type_mismatch_columns"],
        unseen_category_columns=quality["unseen_category_columns"],
        out_of_range_columns=quality["out_of_range_columns"],
        outlier_counts=quality["outlier_counts"],
        per_column=quality["per_column"],
        penalties=quality["penalties"],
        quality_score=quality["quality_score"],
    )

    PerformanceSnapshot.objects.create(
        run=run,
        labels_available=perf["labels_available"],
        sample_count=perf["sample_count"],
        accuracy=perf["accuracy"],
        error_rate=perf["error_rate"],
        precision_positive=perf["precision_positive"],
        recall_positive=perf["recall_positive"],
        f1_positive=perf["f1_positive"],
        precision_macro=perf["precision_macro"],
        recall_macro=perf["recall_macro"],
        f1_macro=perf["f1_macro"],
        positive_class=perf.get("positive_class") or "",
        confusion_matrix=perf["confusion_matrix"],
        prediction_distribution=perf["prediction_distribution"],
    )

    batch.status = BatchStatus.COMPLETED
    batch.save(update_fields=["status"])


def _evaluate_alerts(run):
    """Separate transaction: an alerting bug must not undo a valid run."""
    try:
        with transaction.atomic():
            from alerts.retrain import evaluate_retrain
            from alerts.services import evaluate

            evaluate(run)
            evaluate_retrain(run)
    except Exception:  # noqa: BLE001
        logger.exception("alert evaluation failed for run %s", run.pk)


def _raise_batch_rejected(ml_model, message):
    try:
        from alerts.services import create_or_update_alert
        from core.constants import AlertCategory, AlertSeverity

        create_or_update_alert(
            ml_model=ml_model,
            severity=AlertSeverity.WARNING,
            category=AlertCategory.SYSTEM,
            headline="Batch rejected",
            message=message,
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not raise BATCH_REJECTED alert")


def _raise_run_failed(ml_model, run, message):
    try:
        from alerts.services import create_or_update_alert
        from core.constants import AlertCategory, AlertSeverity

        create_or_update_alert(
            ml_model=ml_model,
            severity=AlertSeverity.CRITICAL,
            category=AlertCategory.SYSTEM,
            headline=f"Monitoring run #{run.pk} failed",
            message=message[:1000],
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not raise RUN_FAILED alert")


def ingest_csv(ml_model, file_obj, **kwargs):
    """Convenience wrapper for the upload path."""
    from datasets.services import read_csv

    frame = read_csv(file_obj)
    file_obj.seek(0)
    return ingest_batch(
        ml_model,
        frame,
        file_obj=file_obj,
        original_filename=getattr(file_obj, "name", ""),
        **kwargs,
    )
