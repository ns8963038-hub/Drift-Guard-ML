import pytest
from accounts.models import User
from registry.models import MLModel
from alerts.models import ThresholdProfile, Alert
from alerts.services import resolve_thresholds, create_or_update_alert
from alerts.email import send_alert_email
from core.constants import Role, ProblemType, AlertCategory, AlertSeverity, AlertStatus


@pytest.mark.django_db
def test_threshold_resolution_fallback():
    user = User.objects.create_user(username="u", password="p", role=Role.ML_ENGINEER)
    model = MLModel.objects.create(
        name="M1",
        slug="m1",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )

    # 1. Defaults fallback
    res = resolve_thresholds(model)
    assert res["ks_p_value_threshold"] == 0.05
    assert res["health_warning_threshold"] == 70

    # 2. Global profile fallback
    ThresholdProfile.objects.create(ml_model=None, ks_p_value_threshold=0.01)
    res_global = resolve_thresholds(model)
    assert res_global["ks_p_value_threshold"] == 0.01

    # 3. Model-specific profile override
    ThresholdProfile.objects.create(ml_model=model, ks_p_value_threshold=0.001)
    res_model = resolve_thresholds(model)
    assert res_model["ks_p_value_threshold"] == 0.001


@pytest.mark.django_db
def test_alert_deduplication_cooldown():
    user = User.objects.create_user(username="u2", password="p", role=Role.ML_ENGINEER)
    model = MLModel.objects.create(
        name="M2",
        slug="m2",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )

    # 20 consecutive high drift runs produce ONE alert with occurrence_count == 20
    for _ in range(20):
        create_or_update_alert(
            ml_model=model,
            category=AlertCategory.DRIFT,
            severity=AlertSeverity.CRITICAL,
            feature_name="tenure",
            headline="High Drift Detected",
            message="Feature tenure exhibits high drift.",
        )

    alerts = Alert.objects.filter(ml_model=model, category=AlertCategory.DRIFT)
    assert alerts.count() == 1
    alert = alerts.first()
    assert alert.occurrence_count == 20
    assert alert.status == AlertStatus.NEW


@pytest.mark.django_db
def test_email_failure_swallowed():
    user = User.objects.create_user(
        username="u3", password="p", role=Role.ML_ENGINEER, email="u3@example.com"
    )
    model = MLModel.objects.create(
        name="M3",
        slug="m3",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )
    alert = Alert.objects.create(
        ml_model=model,
        category=AlertCategory.HEALTH,
        severity=AlertSeverity.CRITICAL,
        headline="Health Failure",
        message="Critical drop.",
    )

    # Calling send_alert_email returns False when EMAIL_ENABLED=False without throwing any exception
    sent = send_alert_email(alert)
    assert sent is False
