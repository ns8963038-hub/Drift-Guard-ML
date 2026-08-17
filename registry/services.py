import os
import tempfile
import joblib
from django.db import transaction
from django.core.exceptions import ValidationError

from registry.models import ModelVersion, ModelAuditLog
from core.validators import compute_sha256
from core.constants import (
    VersionStatus,
    ValidationStatus,
    AuditAction,
)
from datasets.services import get_validation_sample


def validate_model_artifact(artifact_file, ml_model):
    """
    Implements the 5-check validation gate (PRD §4.3):
    1. Deserialises via joblib.load
    2. Has a callable .predict()
    3. Predicts successfully on 50 baseline rows
    4. Output length equals input length
    5. Output classes are a subset of the baseline target's classes
    """
    # 1. Deserialization check
    try:
        # Save temporary file to disk for joblib deserialization
        with tempfile.NamedTemporaryFile(delete=False, suffix=".joblib") as tmp:
            for chunk in artifact_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        artifact_file.seek(0)
        model_obj = joblib.load(tmp_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise ValidationError(
            f"Check 1 Failed: Unable to deserialise model artifact via joblib ({str(e)})."
        )

    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    # 2. Predict method check
    if not hasattr(model_obj, "predict") or not callable(getattr(model_obj, "predict")):
        raise ValidationError(
            "Check 2 Failed: Model object lacks a callable '.predict()' method."
        )

    # 3. Predict on 50 baseline rows check
    sample_df, target_classes = get_validation_sample(ml_model, n=50)
    try:
        predictions = model_obj.predict(sample_df)
    except Exception as e:
        raise ValidationError(
            f"Check 3 Failed: Model prediction failed on 50 baseline sample rows ({str(e)})."
        )

    # 4. Output shape match check
    if len(predictions) != len(sample_df):
        raise ValidationError(
            f"Check 4 Failed: Output length ({len(predictions)}) does not match input length ({len(sample_df)})."
        )

    # 5. Output classes subset check
    if target_classes:
        pred_set = set(predictions)
        target_set = set(target_classes)
        if not pred_set.issubset(target_set):
            raise ValidationError(
                f"Check 5 Failed: Predicted classes {pred_set} contain values outside target classes {target_set}."
            )

    return True


@transaction.atomic
def create_model_version(
    ml_model, artifact_file, label=None, user=None, changelog="", training_accuracy=None
):
    """
    Validates artifact and creates a new ModelVersion row.
    If validation fails, raises ValidationError and creates NO database row.
    """
    # Run 5-check validation gate
    validate_model_artifact(artifact_file, ml_model)

    # FR-02.8: fingerprint and size are recorded for every artifact. The hash is
    # one of the stated mitigations for accepted risk R1 — uploaded pickles
    # execute code on load, so being able to prove which bytes were loaded
    # matters. Computed after validation so a rejected file leaves no trace.
    file_hash = compute_sha256(artifact_file)
    file_size = artifact_file.size
    algorithm_name = _detect_algorithm(artifact_file)

    # Calculate next version number
    last_version = ml_model.versions.order_by("-version_number").first()
    next_number = (last_version.version_number + 1) if last_version else 1
    version_label = label or f"V{next_number}"

    version = ModelVersion.objects.create(
        ml_model=ml_model,
        version_number=next_number,
        label=version_label,
        artifact=artifact_file,
        status=VersionStatus.INACTIVE,
        validation_status=ValidationStatus.PASSED,
        validation_message="All five checks passed.",
        file_hash=file_hash,
        file_size=file_size,
        algorithm_name=algorithm_name,
        changelog=changelog,
        training_accuracy=training_accuracy,
        uploaded_by=user,
    )

    # Audit log
    ModelAuditLog.objects.create(
        ml_model=ml_model,
        actor=user,
        action=AuditAction.VERSION_UPLOADED,
        details={
            "version_id": version.id,
            "label": version_label,
            "version_number": next_number,
        },
    )

    return version


@transaction.atomic
def activate_version(version, user=None):
    """
    Activates a ModelVersion, demoting the previous active version in one transaction.
    Calls monitoring baseline distribution calculation (Contract C2).
    """
    # A version that failed the validation gate must never become the active
    # one. Nothing checked this, so a broken artifact could be activated and
    # would then be loaded to score every subsequent batch — each run failing
    # with an error that points at the batch rather than at the artifact.
    if version.validation_status == ValidationStatus.FAILED:
        raise ValidationError(
            f"Version {version.label} failed validation and cannot be activated. "
            "Upload a working artifact instead."
        )

    version.activate()

    # Log audit entry
    ModelAuditLog.objects.create(
        ml_model=version.ml_model,
        actor=user,
        action=AuditAction.VERSION_ACTIVATED,
        details={"version_id": version.id, "label": version.label},
    )
    return version


def _detect_algorithm(artifact_file):
    """Best-effort estimator name for display, e.g. "RandomForestClassifier".

    Never raises: this is a label on a screen, and an artifact that has already
    passed the validation gate must not be rejected because we could not name it.
    """
    try:
        import joblib

        artifact_file.seek(0)
        model = joblib.load(artifact_file)
        artifact_file.seek(0)
        if hasattr(model, "steps"):  # sklearn Pipeline — name the final step
            return type(model.steps[-1][1]).__name__
        return type(model).__name__
    except Exception:
        return ""
