"""Baseline datasets and arriving production batches — TRD §4.3."""

from django.db import models

from core.constants import BatchSource, BatchStatus
from core.models import TimeStampedModel


class BaselineDataset(TimeStampedModel):
    """The training/reference data a model version is judged against.

    Profiled **once** at upload and stored as JSON. No monitoring run ever
    re-reads the source CSV — re-profiling per run would be slow and, worse,
    would let the reference move.
    """

    ml_model = models.ForeignKey(
        "registry.MLModel", on_delete=models.CASCADE, related_name="baselines"
    )
    model_version = models.OneToOneField(
        "registry.ModelVersion",
        on_delete=models.CASCADE,
        related_name="baseline",
        null=True,
        blank=True,
    )

    file = models.FileField(upload_to="datasets/baselines/")
    original_filename = models.CharField(max_length=255, blank=True)
    checksum = models.CharField(max_length=64, blank=True)

    row_count = models.IntegerField(default=0)
    column_count = models.IntegerField(default=0)

    # Per-column type, target flag, exclusion flag and reason.
    schema = models.JSONField(default=dict)
    # Bin edges, bin counts, category frequencies and summary statistics.
    profile = models.JSONField(default=dict)

    # Raw rows for the K-S test, which needs samples rather than bins. Capped
    # and seeded at write time so results stay reproducible (PRD NFR-14).
    reference_sample = models.FileField(
        upload_to="datasets/reference/", null=True, blank=True
    )

    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_baselines",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Baseline for {self.ml_model.name} ({self.row_count:,} rows)"

    @property
    def feature_names(self):
        return [c for c, spec in self.schema.items() if spec.get("is_feature")]


class DataBatch(TimeStampedModel):
    """One arriving set of production rows, however it arrived."""

    ml_model = models.ForeignKey(
        "registry.MLModel", on_delete=models.CASCADE, related_name="batches"
    )
    model_version = models.ForeignKey(
        "registry.ModelVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batches",
    )

    source = models.CharField(
        max_length=20, choices=BatchSource.choices, default=BatchSource.UPLOAD
    )
    file = models.FileField(upload_to="datasets/batches/", null=True, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)

    row_count = models.IntegerField(default=0)
    has_labels = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20, choices=BatchStatus.choices, default=BatchStatus.PENDING
    )
    rejection_reason = models.TextField(blank=True)

    submitted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_batches",
    )
    received_at = models.DateTimeField(auto_now_add=True)

    # Position in a simulator scenario; null for uploads and API calls.
    batch_index = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["ml_model", "-received_at"])]

    def __str__(self):
        return f"Batch #{self.pk} for {self.ml_model.name} ({self.row_count:,} rows)"
