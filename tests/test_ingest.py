"""End-to-end tests for the monitoring pipeline through the database.

This is the keystone: real Telco data, a real trained artifact, the real upload
gate, and the real ingest path. If these pass, the vertical slice works — from a
CSV arriving to a run, its feature table, its alerts and its recommendation.
"""

from __future__ import annotations

import pytest

from alerts.models import Alert, RetrainRecommendation
from core.constants import (
    AlertCategory,
    BatchSource,
    DriftStatus,
    RunStatus,
    VersionStatus,
)
from monitoring.models import MonitoringRun
from monitoring.services import IngestionError, ingest_batch
from tests.conftest import FIXTURES_PRESENT, drifted, holdout

requires_fixtures = pytest.mark.skipif(
    not FIXTURES_PRESENT,
    reason="run scripts/prepare_datasets.py then scripts/train_demo_models.py",
)

pytestmark = [pytest.mark.django_db, requires_fixtures]


# ──────────────────────────────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────────────────────────────


def test_baseline_is_profiled_once_at_upload(churn_model):
    ml_model, version, _ = churn_model
    baseline = version.baseline

    assert baseline.row_count == 4225
    assert baseline.profile["feature_count"] == 19
    assert baseline.checksum
    assert baseline.reference_sample, "the K-S test needs stored raw rows"
    assert "customerID" not in baseline.profile["columns"], "excluded column profiled"


def test_activation_records_the_baseline_prediction_mix(churn_model):
    """Contract C2 — the reference the health score's stability arm uses."""
    _, version, _ = churn_model
    distribution = version.baseline_prediction_distribution

    assert distribution
    assert set(distribution) == {"No", "Yes"}
    assert sum(distribution.values()) == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────────────────
# A clean batch
# ──────────────────────────────────────────────────────────────────────


def test_clean_batch_produces_a_healthy_run(churn_model):
    ml_model, _, user = churn_model
    run = ingest_batch(ml_model, holdout(), submitted_by=user)

    assert run.status == RunStatus.COMPLETED
    assert run.overall_drift_status == DriftStatus.NONE
    assert run.features_total == 19
    assert run.features_high == 0
    assert run.health_band == "HEALTHY"
    assert run.labels_available is True
    assert run.duration_ms >= 0

    assert run.feature_results.count() == 19
    assert run.quality.quality_score >= 90
    assert run.performance.accuracy is not None
    assert run.data_batch.status == "COMPLETED"


def test_every_feature_result_carries_its_explanation(churn_model):
    """FR-14.6 — generated at run time and stored, not regenerated on read."""
    ml_model, _, _ = churn_model
    run = ingest_batch(ml_model, holdout())

    for result in run.feature_results.all():
        assert result.explanation
        assert result.feature_name in result.explanation


def test_thresholds_are_snapshotted_onto_the_run(churn_model):
    """FR-13.4 — what makes history immutable."""
    ml_model, _, _ = churn_model
    run = ingest_batch(ml_model, holdout())

    snapshot = run.thresholds_snapshot
    assert snapshot["psi_moderate"] == 0.10
    assert snapshot["psi_high"] == 0.25
    assert snapshot["alpha"] == 0.05


def test_a_clean_run_raises_no_alerts(churn_model):
    ml_model, _, _ = churn_model
    ingest_batch(ml_model, holdout())
    assert Alert.objects.filter(ml_model=ml_model).count() == 0


# ──────────────────────────────────────────────────────────────────────
# A drifted batch
# ──────────────────────────────────────────────────────────────────────


def test_drifted_batch_is_detected_and_alerted(churn_model):
    ml_model, _, _ = churn_model
    run = ingest_batch(ml_model, drifted())

    assert run.status == RunStatus.COMPLETED
    assert run.overall_drift_status == DriftStatus.HIGH
    assert run.features_high >= 2

    by_name = {r.feature_name: r for r in run.feature_results.all()}
    assert by_name["MonthlyCharges"].status == DriftStatus.HIGH
    assert by_name["Contract"].status == DriftStatus.HIGH
    assert by_name["tenure"].status == DriftStatus.NONE, "untouched column stayed clean"

    drift_alerts = Alert.objects.filter(ml_model=ml_model, category=AlertCategory.DRIFT)
    assert drift_alerts.count() >= 2
    assert drift_alerts.filter(feature_name="MonthlyCharges").exists()
    assert drift_alerts.filter(rule_code="DRIFT_HIGH").exists()


def test_high_drift_cannot_be_reported_as_healthy(churn_model):
    """PRD §8.4a coherence cap, verified through the database."""
    ml_model, _, _ = churn_model
    run = ingest_batch(ml_model, drifted())

    assert run.health_band != "HEALTHY"
    if run.health_capped:
        assert run.health_raw_score > run.health_score


def test_retraining_is_recommended_with_its_reasons(churn_model):
    ml_model, _, _ = churn_model
    ingest_batch(ml_model, drifted())

    recommendation = RetrainRecommendation.objects.get(ml_model=ml_model)
    assert recommendation.status == "OPEN"
    assert recommendation.triggers, "FR-10.2 requires the triggers to be named"
    for trigger in recommendation.triggers:
        assert {"trigger", "measured", "threshold"} <= set(trigger)
    assert "advisory only" in recommendation.message


def test_only_one_open_recommendation_per_model(churn_model):
    """FR-10.5 — further triggers update, never stack."""
    ml_model, _, _ = churn_model
    for seed in range(3):
        ingest_batch(ml_model, drifted(seed=seed + 1))

    assert (
        RetrainRecommendation.objects.filter(ml_model=ml_model, status="OPEN").count()
        == 1
    )


# ──────────────────────────────────────────────────────────────────────
# Deduplication — PRD §9.3
# ──────────────────────────────────────────────────────────────────────


def test_repeated_drift_produces_one_alert_not_many(churn_model):
    """The behaviour that keeps the alerts screen usable under a simulator."""
    ml_model, _, _ = churn_model
    for seed in range(6):
        ingest_batch(ml_model, drifted(seed=seed + 10))

    alerts = Alert.objects.filter(
        ml_model=ml_model, category=AlertCategory.DRIFT, feature_name="MonthlyCharges"
    )
    assert alerts.count() == 1, "one alert per (model, category, feature)"
    assert alerts.first().occurrence_count == 6


# ──────────────────────────────────────────────────────────────────────
# The unlabelled path
# ──────────────────────────────────────────────────────────────────────


def test_unlabelled_batch_completes_without_faking_metrics(churn_model):
    """The realistic production case: features arrive, ground truth does not."""
    ml_model, _, _ = churn_model
    run = ingest_batch(ml_model, holdout().drop(columns=["Churn"]))

    assert run.status == RunStatus.COMPLETED
    assert run.labels_available is False
    assert run.performance.accuracy is None, "unknown accuracy is not zero accuracy"
    assert run.performance.prediction_distribution["total"] == 600
    assert run.feature_results.count() == 19
    assert run.health_components["weighting"] == "without_labels"
    assert run.health_band == "HEALTHY", "an unlabelled batch is not a sick model"


# ──────────────────────────────────────────────────────────────────────
# Rejection and failure paths
# ──────────────────────────────────────────────────────────────────────


def test_batch_missing_a_required_column_is_rejected(churn_model):
    ml_model, _, _ = churn_model
    with pytest.raises(IngestionError, match="missing"):
        ingest_batch(ml_model, holdout().drop(columns=["MonthlyCharges"]))

    batch = ml_model.batches.first()
    assert batch.status == "REJECTED"
    assert "MonthlyCharges" in batch.rejection_reason
    assert MonitoringRun.objects.filter(ml_model=ml_model).count() == 0
    assert Alert.objects.filter(category=AlertCategory.SYSTEM).exists()


def test_extra_columns_are_ignored(churn_model):
    ml_model, _, _ = churn_model
    batch = holdout()
    batch["some_new_column"] = 1
    run = ingest_batch(ml_model, batch)

    assert run.status == RunStatus.COMPLETED
    assert run.features_total == 19


def test_deactivated_model_refuses_batches(churn_model):
    ml_model, _, _ = churn_model
    ml_model.is_active = False
    ml_model.save(update_fields=["is_active"])

    with pytest.raises(IngestionError, match="deactivated"):
        ingest_batch(ml_model, holdout())


def test_model_without_an_active_version_refuses_batches(churn_model):
    ml_model, version, _ = churn_model
    version.status = VersionStatus.INACTIVE
    version.save(update_fields=["status"])

    with pytest.raises(IngestionError, match="no active version"):
        ingest_batch(ml_model, holdout())


# ──────────────────────────────────────────────────────────────────────
# Bookkeeping
# ──────────────────────────────────────────────────────────────────────


def test_batch_source_is_recorded(churn_model):
    ml_model, _, _ = churn_model
    run = ingest_batch(ml_model, holdout(), source=BatchSource.SIMULATOR, batch_index=7)

    assert run.data_batch.source == BatchSource.SIMULATOR
    assert run.data_batch.batch_index == 7
    assert run.trigger_source == "SCHEDULED"


def test_history_survives_a_threshold_change(churn_model):
    """FR-13.4 — editing a threshold must not rewrite a recorded verdict."""
    from alerts.models import ThresholdProfile

    ml_model, _, _ = churn_model
    run = ingest_batch(ml_model, holdout())
    original_status = run.overall_drift_status
    original_snapshot = dict(run.thresholds_snapshot)

    ThresholdProfile.objects.create(
        ml_model=ml_model, psi_moderate=0.0001, psi_high=0.0002
    )

    run.refresh_from_db()
    assert run.overall_drift_status == original_status
    assert run.thresholds_snapshot == original_snapshot
