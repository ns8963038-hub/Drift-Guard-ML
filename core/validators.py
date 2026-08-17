import hashlib
import os
from django.core.exceptions import ValidationError

ALLOWED_MODEL_EXTENSIONS = [".pkl", ".joblib"]
ALLOWED_DATASET_EXTENSIONS = [".csv", ".parquet"]
# TRD §9: artifacts cap at 100 MB, CSV datasets at 50 MB. One shared limit let a
# 90 MB CSV through a gate meant to stop it.
MAX_MODEL_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB — PRD FR-02.8
MAX_DATASET_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB  — TRD §9

# Retained for callers that predate the split.
MAX_UPLOAD_SIZE_BYTES = MAX_MODEL_SIZE_BYTES


def validate_file_extension(value, allowed_extensions):
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in allowed_extensions:
        raise ValidationError(
            f"Unsupported file extension '{ext}'. Allowed extensions are: {', '.join(allowed_extensions)}"
        )


def validate_model_file_extension(value):
    validate_file_extension(value, ALLOWED_MODEL_EXTENSIONS)


def validate_dataset_file_extension(value):
    validate_file_extension(value, ALLOWED_DATASET_EXTENSIONS)


def validate_file_size(value, max_bytes=MAX_MODEL_SIZE_BYTES):
    if value.size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        raise ValidationError(
            f"File size exceeds maximum allowed limit of {max_mb:.0f} MB."
        )


def validate_model_file_size(value):
    validate_file_size(value, MAX_MODEL_SIZE_BYTES)


def validate_dataset_file_size(value):
    validate_file_size(value, MAX_DATASET_SIZE_BYTES)


def compute_sha256(file_obj):
    sha256 = hashlib.sha256()
    for chunk in file_obj.chunks():
        sha256.update(chunk)
    file_obj.seek(0)
    return sha256.hexdigest()
