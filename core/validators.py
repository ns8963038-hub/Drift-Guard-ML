import hashlib
import os
from django.core.exceptions import ValidationError

ALLOWED_MODEL_EXTENSIONS = [".pkl", ".joblib"]
ALLOWED_DATASET_EXTENSIONS = [".csv", ".parquet"]
MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


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


def validate_file_size(value):
    if value.size > MAX_UPLOAD_SIZE_BYTES:
        max_mb = MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)
        raise ValidationError(
            f"File size exceeds maximum allowed limit of {max_mb:.0f} MB."
        )


def compute_sha256(file_obj):
    sha256 = hashlib.sha256()
    for chunk in file_obj.chunks():
        sha256.update(chunk)
    file_obj.seek(0)
    return sha256.hexdigest()
