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
    ml_model = models.OneToOneField(
        "registry.MLModel",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="threshold_profile",
    )
    ks_p_value_threshold = models.FloatField(default=0.05)
    chi2_p_value_threshold = models.FloatField(default=0.05)
    psi_threshold = models.FloatField(default=0.2)
    js_threshold = models.FloatField(default=0.1)
    missing_value_rate_threshold = models.FloatField(default=0.05)
    duplicate_row_rate_threshold = models.FloatField(default=0.01)
    outlier_rate_threshold = models.FloatField(default=0.05)
    accuracy_drop_threshold = models.FloatField(default=0.05)
    health_warning_threshold = models.IntegerField(default=70)
    health_critical_threshold = models.IntegerField(default=50)

    def is_global(self):
        return self.ml_model is None


class Alert(models.Model):
    ml_model = models.ForeignKey(
        "registry.MLModel", on_delete=models.CASCADE, related_name="alerts"
    )
    run_id = models.IntegerField(null=True, blank=True)
    severity = models.CharField(max_length=20, choices=AlertSeverity.choices)
    category = models.CharField(max_length=20, choices=AlertCategory.choices)
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
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen_at"]


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
    severity = models.CharField(max_length=20, choices=RetrainSeverity.choices)
    triggers = models.JSONField(default=list)
    status = models.CharField(
        max_length=20, choices=RetrainStatus.choices, default=RetrainStatus.OPEN
    )

    class Meta:
        ordering = ["-created_at"]
