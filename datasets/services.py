"""Baseline ingestion and batch loading.

The one rule that governs this module: a baseline is profiled **once**, at
upload, and every later monitoring run reads the stored profile. Re-profiling
per run would be slow, and worse, it would let the reference distribution move —
which is precisely the thing drift detection exists to measure against.
"""

from __future__ import annotations

import hashlib
import io

import pandas as pd
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from datasets.models import BaselineDataset
from monitoring.engine import profiling

# The K-S test needs raw samples rather than bins, so a slice of the baseline is
# kept alongside the profile. Capped for runtime and seeded for reproducibility
# (PRD NFR-14).
REFERENCE_SAMPLE_MAX_ROWS = 50_000
SAMPLE_SEED = 42

MIN_BASELINE_ROWS = 100


def read_csv(file_obj) -> pd.DataFrame:
    """Read an uploaded CSV, raising a message a user can act on."""
    try:
        file_obj.seek(0)
        frame = pd.read_csv(file_obj)
    except Exception as exc:  # noqa: BLE001 — surfaced to the upload form
        raise ValidationError(f"Could not read the CSV: {exc}") from exc

    if frame.empty:
        raise ValidationError("The file contains no rows.")
    return frame


@transaction.atomic
def create_baseline_dataset(
    ml_model,
    model_version,
    file_obj,
    target_column,
    user=None,
    schema_overrides=None,
):
    """Profile an uploaded baseline and store it against a model version.

    ``schema_overrides`` lets the upload screen correct the inferred column
    types and exclusions before anything is stored — the heuristic cannot know
    that ``area_code`` is a real feature rather than an identifier (FR-08.4).
    """
    frame = read_csv(file_obj)

    if target_column not in frame.columns:
        raise ValidationError(
            f"Target column '{target_column}' is not in the file. "
            f"Columns found: {', '.join(frame.columns[:12])}"
        )
    if len(frame) < MIN_BASELINE_ROWS:
        raise ValidationError(
            f"A baseline needs at least {MIN_BASELINE_ROWS} rows; this file has {len(frame)}."
        )
    if frame[target_column].nunique(dropna=True) < 2:
        raise ValidationError(
            f"The target column '{target_column}' has fewer than two distinct "
            f"values, so no classifier can be evaluated against it."
        )

    schema = profiling.infer_schema(frame, target_column)

    for column, override in (schema_overrides or {}).items():
        if column in schema:
            schema[column].update(override)

    profile = profiling.build_profile(frame, schema)

    file_obj.seek(0)
    checksum = hashlib.sha256(file_obj.read()).hexdigest()
    file_obj.seek(0)

    baseline = BaselineDataset.objects.create(
        ml_model=ml_model,
        model_version=model_version,
        file=file_obj,
        original_filename=getattr(file_obj, "name", "")[:255],
        checksum=checksum,
        row_count=len(frame),
        column_count=frame.shape[1],
        schema=schema,
        profile=profile,
        uploaded_by=user,
    )

    _store_reference_sample(baseline, frame, schema)
    return baseline


def _store_reference_sample(baseline, frame, schema):
    """Persist the raw rows the K-S test compares against, as parquet."""
    columns = profiling.feature_columns(schema)
    sample = frame[columns]

    if len(sample) > REFERENCE_SAMPLE_MAX_ROWS:
        sample = sample.sample(REFERENCE_SAMPLE_MAX_ROWS, random_state=SAMPLE_SEED)

    buffer = io.BytesIO()
    sample.to_parquet(buffer, index=False)
    baseline.reference_sample.save(
        f"reference_{baseline.pk}.parquet", ContentFile(buffer.getvalue()), save=True
    )


def load_reference_sample(baseline) -> pd.DataFrame:
    """Read back the stored reference rows.

    Falls back to the source CSV if the parquet is missing, so a baseline
    uploaded before the sample existed still works rather than failing the run.
    """
    if baseline.reference_sample:
        try:
            baseline.reference_sample.open("rb")
            return pd.read_parquet(baseline.reference_sample)
        finally:
            baseline.reference_sample.close()

    baseline.file.open("rb")
    try:
        return pd.read_csv(baseline.file)
    finally:
        baseline.file.close()


def get_active_baseline(ml_model):
    """The baseline for the model's active version, or the most recent one.

    Versions may share a baseline, and a model can have a baseline uploaded
    before any version was activated, so this deliberately does not require a
    version link.
    """
    active_version = ml_model.versions.filter(status="ACTIVE").first()
    if active_version is not None:
        linked = BaselineDataset.objects.filter(model_version=active_version).first()
        if linked is not None:
            return linked
    return (
        BaselineDataset.objects.filter(ml_model=ml_model)
        .order_by("-created_at")
        .first()
    )


def get_validation_sample(ml_model, n=50):
    """Contract C1 — rows for the PRD §4.3 upload validation gate.

    Returns ``(DataFrame of raw feature columns, list of target classes)``. The
    frame carries only the columns the model is expected to accept, so check 3
    of the gate genuinely exercises the artifact's own preprocessing rather than
    handing it a shape it never saw in training.
    """
    baseline = get_active_baseline(ml_model)
    if baseline is None:
        raise ValidationError(
            "This model has no baseline dataset yet. Upload one before uploading "
            "a model version — the validation gate needs real rows to score."
        )

    frame = load_reference_sample(baseline)
    features = [c for c in baseline.feature_names if c in frame.columns]
    sample = frame[features].head(n)

    target = profiling.target_column(baseline.schema)
    classes = []
    if target:
        baseline.file.open("rb")
        try:
            source = pd.read_csv(baseline.file, usecols=[target])
            classes = sorted(source[target].dropna().astype(str).unique())
        except Exception:  # noqa: BLE001 — classes are advisory for the gate
            classes = []
        finally:
            baseline.file.close()

    return sample, classes
