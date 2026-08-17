from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    DATA_SCIENTIST = "DATA_SCIENTIST", "Data Scientist"
    ML_ENGINEER = "ML_ENGINEER", "ML Engineer"


class Permission(models.TextChoices):
    VIEW = "VIEW", "View"
    MANAGE = "MANAGE", "Manage"


class ProblemType(models.TextChoices):
    BINARY = "BINARY", "Binary Classification"
    MULTICLASS = "MULTICLASS", "Multiclass Classification"


class VersionStatus(models.TextChoices):
    INACTIVE = "INACTIVE", "Inactive"
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class ValidationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PASSED = "PASSED", "Passed"
    FAILED = "FAILED", "Failed"


class BatchSource(models.TextChoices):
    UPLOAD = "UPLOAD", "Upload"
    SIMULATOR = "SIMULATOR", "Simulator"
    API = "API", "API"


class BatchStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    VALIDATING = "VALIDATING", "Validating"
    PROCESSING = "PROCESSING", "Processing"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"
    REJECTED = "REJECTED", "Rejected"


class RunStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    RUNNING = "RUNNING", "Running"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class TriggerSource(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    SCHEDULED = "SCHEDULED", "Scheduled"
    UPLOAD = "UPLOAD", "Upload"
    API = "API", "API"


class FeatureType(models.TextChoices):
    NUMERIC = "NUMERIC", "Numeric"
    CATEGORICAL = "CATEGORICAL", "Categorical"


class TestName(models.TextChoices):
    KS = "KS", "Kolmogorov-Smirnov"
    CHI2 = "CHI2", "Chi-Square"


class DriftStatus(models.TextChoices):
    NONE = "NONE", "None"
    MODERATE = "MODERATE", "Moderate"
    HIGH = "HIGH", "High"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA", "Insufficient Data"


class HealthBand(models.TextChoices):
    HEALTHY = "HEALTHY", "Healthy"
    WARNING = "WARNING", "Warning"
    CRITICAL = "CRITICAL", "Critical"


class AlertSeverity(models.TextChoices):
    INFO = "INFO", "Info"
    WARNING = "WARNING", "Warning"
    CRITICAL = "CRITICAL", "Critical"


class AlertCategory(models.TextChoices):
    DRIFT = "DRIFT", "Drift"
    PERFORMANCE = "PERFORMANCE", "Performance"
    QUALITY = "QUALITY", "Quality"
    HEALTH = "HEALTH", "Health"
    RETRAIN = "RETRAIN", "Retrain"
    SYSTEM = "SYSTEM", "System"


class AlertStatus(models.TextChoices):
    NEW = "NEW", "New"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    RESOLVED = "RESOLVED", "Resolved"


class RetrainSeverity(models.TextChoices):
    ADVISED = "ADVISED", "Advised"
    URGENT = "URGENT", "Urgent"


class RetrainStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    DISMISSED = "DISMISSED", "Dismissed"


class ScenarioStatus(models.TextChoices):
    STOPPED = "STOPPED", "Stopped"
    RUNNING = "RUNNING", "Running"
    PAUSED = "PAUSED", "Paused"


class LoginEvent(models.TextChoices):
    LOGIN_SUCCESS = "LOGIN_SUCCESS", "Login Success"
    LOGIN_FAILED = "LOGIN_FAILED", "Login Failed"
    LOGOUT = "LOGOUT", "Logout"


class AuditAction(models.TextChoices):
    MODEL_CREATED = "MODEL_CREATED", "Model Created"
    VERSION_UPLOADED = "VERSION_UPLOADED", "Version Uploaded"
    VERSION_ACTIVATED = "VERSION_ACTIVATED", "Version Activated"
    VERSION_DEACTIVATED = "VERSION_DEACTIVATED", "Version Deactivated"
    VERSION_ARCHIVED = "VERSION_ARCHIVED", "Version Archived"
    BASELINE_UPLOADED = "BASELINE_UPLOADED", "Baseline Uploaded"
    THRESHOLDS_CHANGED = "THRESHOLDS_CHANGED", "Thresholds Changed"
    MODEL_DEACTIVATED = "MODEL_DEACTIVATED", "Model Deactivated"
