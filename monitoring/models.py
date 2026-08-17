"""Monitoring runs and their results — TRD §4.4.

``MonitoringRun`` is the historical record the whole product is built around:
every chart, alert, comparison and history screen reads from it or its children.

Two properties make the history trustworthy:

* **Immutable.** Each run stores the thresholds it was judged under
  (``thresholds_snapshot``), so editing a threshold today leaves last week's
  verdicts exactly as they were (PRD FR-13.4).
* **Denormalised counters.** ``features_high`` and friends live on the run
  rather than being aggregated from the child table, so list views and charts
  never fan out across thousands of feature rows.
"""

from django.db import models

from core.constants import (
    DriftStatus,
    FeatureType,
    HealthBand,
    RunStatus,
    TestName,
    TriggerSource,
)
from core.models import TimeStampedModel


class MonitoringRun(TimeStampedModel):
    ml_model = models.ForeignKey(
        "registry.MLModel", on_delete=models.CASCADE, related_name="runs"
    )
    model_version = models.ForeignKey(
        "registry.ModelVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    data_batch = models.OneToOneField(
        "datasets.DataBatch",
        on_delete=models.CASCADE,
        related_name="run",
        null=True,
        blank=True,
    )

    trigger_source = models.CharField(
        max_length=20, choices=TriggerSource.choices, default=TriggerSource.MANUAL
    )
    status = models.CharField(
        max_length=20, choices=RunStatus.choices, default=RunStatus.QUEUED
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)

    # ── drift roll-up (PRD §7.4) ──────────────────────────────────────
    overall_drift_status = models.CharField(
        max_length=25, choices=DriftStatus.choices, default=DriftStatus.NONE
    )
    features_total = models.IntegerField(default=0)
    features_high = models.IntegerField(default=0)
    features_moderate = models.IntegerField(default=0)
    features_insufficient = models.IntegerField(default=0)

    # ── health (PRD §8) ───────────────────────────────────────────────
    health_score = models.IntegerField(null=True, blank=True)
    # The uncapped figure, kept so the §8.4a coherence cap is auditable rather
    # than invisible.
    health_raw_score = models.IntegerField(null=True, blank=True)
    health_capped = models.BooleanField(default=False)
    health_band = models.CharField(
        max_length=20, choices=HealthBand.choices, blank=True
    )
    health_components = models.JSONField(default=dict, blank=True)

    labels_available = models.BooleanField(default=False)

    # PRD FR-13.4 — what makes history immutable.
    thresholds_snapshot = models.JSONField(default=dict, blank=True)

    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ml_model", "-created_at"]),
            models.Index(fields=["ml_model", "status"]),
        ]

    def __str__(self):
        return f"Run #{self.pk} · {self.ml_model.name} · {self.overall_drift_status}"

    @property
    def features_clean(self):
        return (
            self.features_total
            - self.features_high
            - self.features_moderate
            - self.features_insufficient
        )


class FeatureDriftResult(models.Model):
    """One row per monitored feature per run — the feature drift table (FR-08)."""

    run = models.ForeignKey(
        MonitoringRun, on_delete=models.CASCADE, related_name="feature_results"
    )
    feature_name = models.CharField(max_length=255)
    feature_type = models.CharField(max_length=20, choices=FeatureType.choices)
    test_name = models.CharField(max_length=10, choices=TestName.choices, blank=True)

    test_statistic = models.FloatField(null=True, blank=True)
    p_value = models.FloatField(null=True, blank=True)
    psi = models.FloatField(null=True, blank=True)
    jsd = models.FloatField(null=True, blank=True)

    status = models.CharField(
        max_length=25, choices=DriftStatus.choices, default=DriftStatus.NONE
    )

    # Generated at run time and stored, never regenerated on read (FR-14.6).
    explanation = models.TextField(blank=True)

    baseline_summary = models.JSONField(default=dict, blank=True)
    current_summary = models.JSONField(default=dict, blank=True)
    unseen_categories = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["feature_name"]
        unique_together = ("run", "feature_name")
        indexes = [models.Index(fields=["run", "status"])]

    def __str__(self):
        return f"{self.feature_name}: {self.status}"


class DataQualityReport(models.Model):
    """The six FR-11 checks for one run."""

    run = models.OneToOneField(
        MonitoringRun, on_delete=models.CASCADE, related_name="quality"
    )

    row_count = models.IntegerField(default=0)
    columns_checked = models.IntegerField(default=0)

    missing_total = models.IntegerField(default=0)
    missing_pct = models.FloatField(default=0.0)
    duplicate_rows = models.IntegerField(default=0)
    duplicate_pct = models.FloatField(default=0.0)
    outlier_pct = models.FloatField(default=0.0)

    type_mismatch_columns = models.JSONField(default=dict, blank=True)
    unseen_category_columns = models.JSONField(default=dict, blank=True)
    out_of_range_columns = models.JSONField(default=dict, blank=True)
    outlier_counts = models.JSONField(default=dict, blank=True)
    per_column = models.JSONField(default=dict, blank=True)

    # The penalty breakdown, so the score is never a black box.
    penalties = models.JSONField(default=dict, blank=True)
    quality_score = models.IntegerField(default=100)

    def __str__(self):
        return f"Quality {self.quality_score}/100 for run #{self.run_id}"


class PerformanceSnapshot(models.Model):
    """Classification metrics for one run.

    **Every metric is nullable on purpose.** An unlabelled batch has not scored
    zero accuracy — accuracy is unknown, and PRD FR-04.5 forbids representing
    that as 0. Storing zeros would drag every average down, turn the performance
    chart into a cliff and fire alerts about a healthy model.
    """

    run = models.OneToOneField(
        MonitoringRun, on_delete=models.CASCADE, related_name="performance"
    )

    labels_available = models.BooleanField(default=False)
    sample_count = models.IntegerField(default=0)

    accuracy = models.FloatField(null=True, blank=True)
    error_rate = models.FloatField(null=True, blank=True)

    precision_positive = models.FloatField(null=True, blank=True)
    recall_positive = models.FloatField(null=True, blank=True)
    f1_positive = models.FloatField(null=True, blank=True)

    precision_macro = models.FloatField(null=True, blank=True)
    recall_macro = models.FloatField(null=True, blank=True)
    f1_macro = models.FloatField(null=True, blank=True)

    positive_class = models.CharField(max_length=100, blank=True)
    confusion_matrix = models.JSONField(null=True, blank=True)
    prediction_distribution = models.JSONField(default=dict, blank=True)

    def __str__(self):
        if not self.labels_available:
            return f"Run #{self.run_id}: no labels"
        return f"Run #{self.run_id}: accuracy {self.accuracy:.4f}"
