"""Baseline upload (S8) and production batch upload (S15)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from core.constants import BatchSource, Permission, Role
from core.mixins import model_permission_required, role_required, visible_models
from core.validators import (
    validate_dataset_file_extension,
    validate_dataset_file_size,
)
from datasets.services import create_baseline_dataset, get_active_baseline, read_csv
from monitoring.services import IngestionError, ingest_batch


@login_required
@role_required(Role.DATA_SCIENTIST)
@model_permission_required(Permission.MANAGE)
def baseline_upload_view(request, slug):
    """S8 — upload the reference data a model is judged against.

    The inferred schema is shown for confirmation before anything is stored,
    because the exclusion heuristic cannot know that a column named like an
    identifier is actually a feature (FR-08.4).
    """
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    existing = get_active_baseline(ml_model)

    if request.method == "POST":
        upload = request.FILES.get("dataset")
        if upload is None:
            messages.error(request, "Choose a CSV file to upload.")
            return redirect("datasets:baseline_upload", slug=slug)

        try:
            validate_dataset_file_extension(upload)
            validate_dataset_file_size(upload)

            excluded = set(request.POST.getlist("exclude"))
            overrides = {
                column: {
                    "is_feature": False,
                    "excluded": True,
                    "exclusion_reason": "Excluded by the uploader",
                }
                for column in excluded
            }

            baseline = create_baseline_dataset(
                ml_model,
                ml_model.versions.filter(status="ACTIVE").first(),
                upload,
                target_column=request.POST.get("target_column")
                or ml_model.target_column,
                user=request.user,
                schema_overrides=overrides,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("datasets:baseline_upload", slug=slug)

        messages.success(
            request,
            f"Baseline uploaded: {baseline.row_count:,} rows, "
            f"{len(baseline.feature_names)} features monitored.",
        )
        return redirect("registry:overview", slug=slug)

    return render(
        request,
        "datasets/baseline_upload.html",
        {"ml_model": ml_model, "existing": existing, "tab": "overview"},
    )


@login_required
@model_permission_required(Permission.VIEW)
def batch_upload_view(request, slug):
    """S15 — submit a batch of production rows for monitoring.

    Open to ML Engineers as well: feeding production data in is their job
    (PRD §5.2), and it is the only write action their role permits.
    """
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    if request.method == "POST":
        upload = request.FILES.get("batch")
        if upload is None:
            messages.error(request, "Choose a CSV file to upload.")
            return redirect("datasets:batch_upload", slug=slug)

        try:
            validate_dataset_file_extension(upload)
            validate_dataset_file_size(upload)
            frame = read_csv(upload)
            upload.seek(0)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("datasets:batch_upload", slug=slug)

        try:
            run = ingest_batch(
                ml_model,
                frame,
                source=BatchSource.UPLOAD,
                submitted_by=request.user,
                file_obj=upload,
                original_filename=upload.name,
            )
        except IngestionError as exc:
            messages.error(request, str(exc))
            return redirect("datasets:batch_upload", slug=slug)

        if run is None:
            messages.warning(
                request,
                "A monitoring run for this model is already in progress. "
                "Try again in a moment.",
            )
            return redirect("registry:overview", slug=slug)

        if run.status == "FAILED":
            messages.error(request, f"The run failed: {run.error_message}")
        else:
            messages.success(
                request,
                f"Batch processed: {run.features_high} high-drift feature(s), "
                f"health {run.health_score}/100.",
            )
        return redirect("monitoring:run_detail", run_id=run.pk)

    baseline = get_active_baseline(ml_model)
    return render(
        request,
        "datasets/batch_upload.html",
        {
            "ml_model": ml_model,
            "baseline": baseline,
            "required_columns": baseline.feature_names if baseline else [],
            "tab": "overview",
            "nav": "models",
        },
    )
