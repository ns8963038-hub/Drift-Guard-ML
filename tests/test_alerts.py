import pytest
from accounts.models import User
from registry.models import MLModel
from alerts.models import ThresholdProfile, Alert
from alerts.services import resolve_thresholds, create_or_update_alert
from alerts.email import send_alert_email
from core.constants import Role, ProblemType, AlertCategory, AlertSeverity, AlertStatus


@pytest.mark.django_db
def test_threshold_resolution_fallback():
    user = User.objects.create_user(username="u", password="p", role=Role.ANALYST)
    model = MLModel.objects.create(
        name="M1",
        slug="m1",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )

    # 1. Defaults fallback — PRD §7.2 bands and §8.4 health bands
    res = resolve_thresholds(model)
    assert res["alpha"] == 0.05
    assert res["psi_moderate"] == 0.10
    assert res["psi_high"] == 0.25
    assert res["health_warning_threshold"] == 80
    assert res["health_critical_threshold"] == 60

    # 2. Global profile fallback
    ThresholdProfile.objects.create(ml_model=None, alpha=0.01)
    assert resolve_thresholds(model)["alpha"] == 0.01

    # 3. Model-specific profile override
    ThresholdProfile.objects.create(ml_model=model, alpha=0.001)
    assert resolve_thresholds(model)["alpha"] == 0.001


@pytest.mark.django_db
def test_resolved_thresholds_satisfy_the_engine_contract():
    """Contract C14 — the engine reads this dict directly and cannot translate.

    The two halves previously shared zero keys, so wiring the pipeline to
    resolve_thresholds() would have raised KeyError on the first monitoring run.
    """
    from monitoring.engine import drift

    resolved = resolve_thresholds(None)
    required = set(drift.default_thresholds())
    missing = required - set(resolved)
    assert not missing, f"engine keys absent from resolve_thresholds(): {missing}"


@pytest.mark.django_db
def test_moderate_band_sits_below_high_band():
    """Without this ordering the amber 🟡 state is unreachable, and the
    🟢→🟡→🔴 progression the client's brief asks for cannot happen."""
    resolved = resolve_thresholds(None)
    assert resolved["psi_moderate"] < resolved["psi_high"]
    assert resolved["jsd_moderate"] < resolved["jsd_high"]
    assert resolved["health_critical_threshold"] < resolved["health_warning_threshold"]


@pytest.mark.django_db
def test_alert_deduplication_cooldown():
    user = User.objects.create_user(username="u2", password="p", role=Role.ANALYST)
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
        username="u3", password="p", role=Role.ANALYST, email="u3@example.com"
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


@pytest.mark.django_db
def test_escalating_alert_updates_its_headline_not_only_its_severity():
    """A deduplicated alert must describe its latest occurrence, not its first.

    Dedup refreshed ``severity`` and ``message`` but left ``headline`` alone, so
    a feature that drifted moderately and then badly showed a WARNING headline
    beside a CRITICAL badge on the one screen used to decide what to act on.
    """
    user = User.objects.create_user(username="esc", password="p", role=Role.ANALYST)
    model = MLModel.objects.create(
        name="Esc",
        slug="esc",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )

    create_or_update_alert(
        ml_model=model,
        category=AlertCategory.DRIFT,
        severity=AlertSeverity.WARNING,
        headline="Moderate drift detected — tenure",
        message="PSI 0.14",
        feature_name="tenure",
        rule_code="DRIFT_MODERATE",
    )
    escalated = create_or_update_alert(
        ml_model=model,
        category=AlertCategory.DRIFT,
        severity=AlertSeverity.CRITICAL,
        headline="High drift detected — tenure",
        message="PSI 0.41",
        feature_name="tenure",
        rule_code="DRIFT_HIGH",
    )

    assert Alert.objects.filter(ml_model=model).count() == 1, "must deduplicate"
    assert escalated.occurrence_count == 2
    assert escalated.severity == AlertSeverity.CRITICAL
    assert escalated.headline == "High drift detected — tenure"
    assert escalated.rule_code == "DRIFT_HIGH"
    assert escalated.message == "PSI 0.41"


@pytest.mark.django_db
def test_recommendation_triggers_render_as_values_not_python_reprs(client):
    """Each trigger is a dict; printing the dict shows a raw Python repr.

    The recommendations screen exists to show *why* retraining is advised, and
    it was rendering {'trigger': '...', 'measured': '...'} braces and all.
    """
    from alerts.models import RetrainRecommendation
    from core.constants import RetrainSeverity, RetrainStatus
    from django.urls import reverse

    user = User.objects.create_user(
        username="recu", password="p", role=Role.DATA_SCIENTIST
    )
    model = MLModel.objects.create(
        name="Rec",
        slug="rec",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )
    from registry.models import ModelVersion

    version = ModelVersion.objects.create(ml_model=model, label="V1")
    RetrainRecommendation.objects.create(
        ml_model=model,
        version=version,
        severity=RetrainSeverity.URGENT,
        status=RetrainStatus.OPEN,
        triggers=[
            {
                "trigger": "Accuracy has fallen",
                "measured": "0.6514",
                "threshold": "5 point drop",
            }
        ],
    )
    client.login(username="recu", password="p")

    body = client.get(reverse("alerts:recommendations")).content.decode()
    assert "Accuracy has fallen" in body
    assert "0.6514" in body
    assert "5 point drop" in body
    assert "{&#x27;trigger&#x27;" not in body and "{'trigger'" not in body
