from django.db import models, transaction
from core.models import TimeStampedModel
from core.constants import (
    ProblemType,
    VersionStatus,
    ValidationStatus,
    AuditAction,
)


class MLModel(TimeStampedModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    target_column = models.CharField(max_length=255)
    positive_class = models.CharField(max_length=255, null=True, blank=True)
    problem_type = models.CharField(max_length=20, choices=ProblemType.choices)
    is_active = models.BooleanField(default=True)
    owner = models.ForeignKey(
        "accounts.User", on_delete=models.RESTRICT, related_name="owned_models"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "ML Model"
        verbose_name_plural = "ML Models"

    def __str__(self):
        return self.name

    @property
    def active_version(self):
        return self.versions.filter(status=VersionStatus.ACTIVE).first()


class ModelVersion(TimeStampedModel):
    ml_model = models.ForeignKey(
        MLModel, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.IntegerField(default=1)
    label = models.CharField(max_length=50)
    artifact = models.FileField(upload_to="models/artifacts/")
    status = models.CharField(
        max_length=20, choices=VersionStatus.choices, default=VersionStatus.INACTIVE
    )
    validation_status = models.CharField(
        max_length=20,
        choices=ValidationStatus.choices,
        default=ValidationStatus.PENDING,
    )
    feature_schema = models.JSONField(default=dict)
    training_accuracy = models.FloatField(null=True, blank=True)
    baseline_prediction_distribution = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-version_number"]
        unique_together = ("ml_model", "version_number")

    def __str__(self):
        return f"{self.ml_model.name} - {self.label}"

    @transaction.atomic
    def activate(self):
        # Demote current ACTIVE versions to INACTIVE for this model
        ModelVersion.objects.filter(
            ml_model=self.ml_model, status=VersionStatus.ACTIVE
        ).update(status=VersionStatus.INACTIVE)
        self.status = VersionStatus.ACTIVE
        self.save(update_fields=["status"])


class ModelAuditLog(models.Model):
    ml_model = models.ForeignKey(
        MLModel, on_delete=models.CASCADE, related_name="audit_logs"
    )
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=50, choices=AuditAction.choices)
    details = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
