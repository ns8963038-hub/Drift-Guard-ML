from datetime import timedelta
from django.utils import timezone
from django.db import transaction

from alerts.models import ThresholdProfile, Alert
from core.constants import (
    AlertSeverity,
    AlertCategory,
    AlertStatus,
)


def resolve_thresholds(ml_model):
    """Contract C14. Resolution order: model profile -> global profile -> code.

    The returned dict is consumed directly by ``monitoring.engine`` and by the
    §9.1 alert rules, so the keys must match
    ``monitoring.engine.drift.default_thresholds()`` exactly. The engine cannot
    import Django and has no way to translate names; a mismatch surfaces as a
    KeyError on the first monitoring run rather than at startup.

    Every run stores a snapshot of what this returned (PRD FR-13.4), which is
    what makes history immutable when someone later edits a threshold.
    """
    profile = None
    if ml_model is not None:
        profile = ThresholdProfile.objects.filter(ml_model=ml_model).first()
    if profile is None:
        profile = ThresholdProfile.objects.filter(ml_model__isnull=True).first()

    if profile is None:
        # No profile stored at all — fall back to the engine's own defaults so a
        # fresh install still runs. Imported lazily: alerts/ is loaded during
        # app registry population, and the engine pulls in scipy.
        from monitoring.engine import drift

        defaults = drift.default_thresholds()
        defaults.update(
            {
                "missing_value_rate_threshold": 0.05,
                "duplicate_row_rate_threshold": 0.01,
                "outlier_rate_threshold": 0.05,
                "accuracy_drop_minor": 0.05,
                "accuracy_drop_major": 0.10,
                "health_warning_threshold": 80,
                "health_critical_threshold": 60,
                "alert_cooldown_minutes": 60,
                "email_enabled": False,
            }
        )
        return defaults

    resolved = profile.as_engine_dict()
    resolved.update(
        {
            "missing_value_rate_threshold": profile.missing_value_rate_threshold,
            "duplicate_row_rate_threshold": profile.duplicate_row_rate_threshold,
            "outlier_rate_threshold": profile.outlier_rate_threshold,
            "accuracy_drop_minor": profile.accuracy_drop_minor,
            "accuracy_drop_major": profile.accuracy_drop_major,
            "health_warning_threshold": profile.health_warning_threshold,
            "health_critical_threshold": profile.health_critical_threshold,
            "alert_cooldown_minutes": profile.alert_cooldown_minutes,
            "email_enabled": profile.email_enabled,
        }
    )
    return resolved


def create_or_update_alert(
    ml_model,
    category,
    severity,
    headline,
    message,
    feature_name="",
    run_id=None,
    cooldown_hours=1,
):
    """
    Deduplicates alerts by key (model, category, feature_name).
    If an unresolved alert exists within the cooldown window, increment occurrence_count
    and update last_seen_at instead of creating duplicate database rows.
    """
    cooldown_threshold = timezone.now() - timedelta(hours=cooldown_hours)

    existing = Alert.objects.filter(
        ml_model=ml_model,
        category=category,
        feature_name=feature_name,
        status__in=[AlertStatus.NEW, AlertStatus.ACKNOWLEDGED],
        last_seen_at__gte=cooldown_threshold,
    ).first()

    if existing:
        existing.occurrence_count += 1
        existing.last_seen_at = timezone.now()
        existing.message = message
        existing.severity = severity
        existing.save(
            update_fields=["occurrence_count", "last_seen_at", "message", "severity"]
        )
        return existing

    alert = Alert.objects.create(
        ml_model=ml_model,
        run_id=run_id,
        severity=severity,
        category=category,
        feature_name=feature_name,
        headline=headline,
        message=message,
        status=AlertStatus.NEW,
        occurrence_count=1,
    )
    return alert


@transaction.atomic
def evaluate(run):
    """
    Contract C15: Evaluates alert rules against a monitoring run.
    """
    if not run or not hasattr(run, "ml_model"):
        return []

    ml_model = run.ml_model
    thresholds = resolve_thresholds(ml_model)
    alerts_created = []

    # Health score evaluation
    health_score = getattr(run, "health_score", 100)
    if health_score is not None:
        if health_score < thresholds["health_critical_threshold"]:
            alert = create_or_update_alert(
                ml_model=ml_model,
                category=AlertCategory.HEALTH,
                severity=AlertSeverity.CRITICAL,
                headline="Critical Model Health Degradation",
                message=f"Model health score dropped to {health_score} (below critical threshold {thresholds['health_critical_threshold']}).",
                run_id=getattr(run, "id", None),
            )
            alerts_created.append(alert)
        elif health_score < thresholds["health_warning_threshold"]:
            alert = create_or_update_alert(
                ml_model=ml_model,
                category=AlertCategory.HEALTH,
                severity=AlertSeverity.WARNING,
                headline="Model Health Warning",
                message=f"Model health score dropped to {health_score} (below warning threshold {thresholds['health_warning_threshold']}).",
                run_id=getattr(run, "id", None),
            )
            alerts_created.append(alert)

    # Feature drift evaluation
    if hasattr(run, "feature_drift_results"):
        for res in run.feature_drift_results.all():
            if getattr(res, "drift_status", "") in ["MODERATE", "HIGH"]:
                severity = (
                    AlertSeverity.CRITICAL
                    if res.drift_status == "HIGH"
                    else AlertSeverity.WARNING
                )
                alert = create_or_update_alert(
                    ml_model=ml_model,
                    category=AlertCategory.DRIFT,
                    severity=severity,
                    feature_name=res.feature_name,
                    headline=f"Feature Drift Detected: {res.feature_name}",
                    message=f"Feature '{res.feature_name}' exhibits {res.drift_status.lower()} drift.",
                    run_id=getattr(run, "id", None),
                )
                alerts_created.append(alert)

    return alerts_created


@transaction.atomic
def sweep(clean_runs_threshold=3):
    """
    Contract C17: Auto-resolves alerts whose condition has cleared for 3 consecutive runs.
    """
    unresolved = Alert.objects.filter(
        status__in=[AlertStatus.NEW, AlertStatus.ACKNOWLEDGED]
    )
    resolved_count = 0

    for alert in unresolved:
        # Check recent runs for the model
        if hasattr(alert.ml_model, "runs"):
            recent_runs = alert.ml_model.runs.order_by("-created_at")[
                :clean_runs_threshold
            ]
            if len(recent_runs) >= clean_runs_threshold:
                # If health alert, verify all 3 runs have health above warning threshold
                if alert.category == AlertCategory.HEALTH:
                    thresholds = resolve_thresholds(alert.ml_model)
                    is_clean = all(
                        getattr(r, "health_score", 100)
                        >= thresholds["health_warning_threshold"]
                        for r in recent_runs
                    )
                    if is_clean:
                        alert.status = AlertStatus.RESOLVED
                        alert.resolved_at = timezone.now()
                        alert.message += " [Auto-resolved — condition cleared]"
                        alert.save(update_fields=["status", "resolved_at", "message"])
                        resolved_count += 1
    return resolved_count
