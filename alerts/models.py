from django.db import models
from core.models import TimeStampedModel
from core.constants import (
    AlertSeverity,
    AlertCategory,
    AlertStatus,
    RetrainSeverity,
    RetrainStatus,
)


class ThresholdProfile(TimeStampedModel):
    """Tunable thresholds, resolved model → global → code defaults.

    **Every drift measure needs two bands, not one.** PRD §7.2 defines
    none / moderate / high for both PSI and JSD, and a single threshold per
    measure collapses that to a binary — which makes the 🟡 MODERATE state
    unreachable. The client's brief asks for 🟢🟡🔴 by name, and the simulator's
    demo scenario is calibrated to land in the amber band at batch 10, so a
    single threshold would break the centrepiece of the demo.

    Field names deliberately match ``monitoring.engine.drift.default_thresholds()``
    key for key. The engine is Django-free and consumes a plain dict; if the
    names diverge, ``resolve_thresholds()`` hands the pipeline a dict it cannot
    read and every run fails on a KeyError.
    """

    ml_model = models.OneToOneField(
        "registry.MLModel",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="threshold_profile",
    )

    # ── Drift magnitude bands — PRD §7.2 ──────────────────────────────
    psi_moderate = models.FloatField(default=0.10)
    psi_high = models.FloatField(default=0.25)
    jsd_moderate = models.FloatField(default=0.10)
    jsd_high = models.FloatField(default=0.20)

    # ── Statistical significance — PRD §7.1 ───────────────────────────
    alpha = models.FloatField(default=0.05)

    # ── Run-level roll-up — PRD §7.4 ──────────────────────────────────
    moderate_ratio_for_high = models.FloatField(default=0.30)
    min_samples = models.IntegerField(default=30)

    # ── Data quality — PRD §8.5 ───────────────────────────────────────
    missing_value_rate_threshold = models.FloatField(default=0.05)
    duplicate_row_rate_threshold = models.FloatField(default=0.01)
    outlier_rate_threshold = models.FloatField(default=0.05)

    # ── Performance and health — PRD §9.1, §8.4 ───────────────────────
    accuracy_drop_minor = models.FloatField(default=0.05)
    accuracy_drop_major = models.FloatField(default=0.10)
    health_warning_threshold = models.IntegerField(default=80)
    health_critical_threshold = models.IntegerField(default=60)

    # ── Alerting — PRD §9.3, FR-06.6 ──────────────────────────────────
    alert_cooldown_minutes = models.IntegerField(default=60)
    email_enabled = models.BooleanField(default=False)

    def is_global(self):
        return self.ml_model is None

    def as_engine_dict(self):
        """The subset the pure-Python engine reads, keyed exactly as it expects."""
        return {
            "psi_moderate": self.psi_moderate,
            "psi_high": self.psi_high,
            "jsd_moderate": self.jsd_moderate,
            "jsd_high": self.jsd_high,
            "alpha": self.alpha,
            "moderate_ratio_for_high": self.moderate_ratio_for_high,
            "min_samples": float(self.min_samples),
        }


class Alert(models.Model):
    ml_model = models.ForeignKey(
        "registry.MLModel", on_delete=models.CASCADE, related_name="alerts"
    )
    # Plain integer until Track A's MonitoringRun exists; converted to a real
    # foreign key in the same migration that introduces that table.
    run_id = models.IntegerField(null=True, blank=True)
    severity = models.CharField(max_length=20, choices=AlertSeverity.choices)
    category = models.CharField(max_length=20, choices=AlertCategory.choices)
    # Which §9.1 rule fired. Stored rather than inferred from the message, so
    # dedup and auto-resolution can match on it without parsing prose.
    rule_code = models.CharField(max_length=50, blank=True)
    feature_name = models.CharField(max_length=255, blank=True)
    headline = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(
        max_length=20, choices=AlertStatus.choices, default=AlertStatus.NEW
    )
    occurrence_count = models.IntegerField(default=1)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    acknowledged_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_alerts",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_alerts",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True)
    email_sent = models.BooleanField(default=False)

    @property
    def title(self):
        """PRD FR-06.2 calls this field `title`; the column is `headline`."""
        return self.headline

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            # The §9.3 deduplication lookup key. Without this index every alert
            # evaluation scans the table, and the simulator evaluates on every
            # tick.
            models.Index(
                fields=["ml_model", "status", "category", "feature_name"],
                name="alert_dedup_idx",
            ),
        ]


class RetrainRecommendation(TimeStampedModel):
    ml_model = models.ForeignKey(
        "registry.MLModel",
        on_delete=models.CASCADE,
        related_name="retrain_recommendations",
    )
    version = models.ForeignKey(
        "registry.ModelVersion",
        on_delete=models.CASCADE,
        related_name="retrain_recommendations",
    )
    run_id = models.IntegerField(null=True, blank=True)
    severity = models.CharField(max_length=20, choices=RetrainSeverity.choices)
    # Every trigger that fired, each with its measured value and threshold.
    # FR-10.2 requires the recommendation to name them, not just say "retrain".
    triggers = models.JSONField(default=list)
    message = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=RetrainStatus.choices, default=RetrainStatus.OPEN
    )
    # FR-10.4: the lifecycle records who acted and why.
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retrain_decisions",
    )
    note = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
