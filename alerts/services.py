from datetime import timedelta
from django.utils import timezone
from django.db import transaction

from alerts.models import ThresholdProfile, Alert
from core.constants import (
    AlertSeverity,
    AlertCategory,
    AlertStatus,
    DriftStatus,
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
    rule_code="",
    cooldown_minutes=None,
):
    """Deduplicate on (model, category, feature_name) — PRD §9.3.

    While an unresolved alert with that key exists inside the cooldown window,
    increment its occurrence counter instead of inserting a row. Without this a
    30-second simulator produces hundreds of identical alerts within minutes and
    the alerts screen becomes unusable.
    """
    if cooldown_minutes is None:
        cooldown_minutes = resolve_thresholds(ml_model).get(
            "alert_cooldown_minutes", 60
        )
    cooldown_threshold = timezone.now() - timedelta(minutes=cooldown_minutes)

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
        rule_code=rule_code,
        feature_name=feature_name,
        headline=headline,
        message=message,
        status=AlertStatus.NEW,
        occurrence_count=1,
    )
    return alert


@transaction.atomic
def evaluate(run):
    """Contract C15 — the PRD §9.1 rule set, evaluated against a completed run.

    Every rule carries a ``rule_code`` so deduplication and the auto-resolve
    sweep can match on it without parsing prose.
    """
    if run is None:
        return []

    ml_model = run.ml_model
    thresholds = resolve_thresholds(ml_model)
    raised = []

    def raise_alert(rule_code, severity, category, headline, message, feature_name=""):
        raised.append(
            create_or_update_alert(
                ml_model=ml_model,
                category=category,
                severity=severity,
                headline=headline,
                message=message,
                feature_name=feature_name,
                run_id=run.pk,
                rule_code=rule_code,
                cooldown_minutes=thresholds.get("alert_cooldown_minutes", 60),
            )
        )

    # ── drift, per feature (§9.1 DRIFT_HIGH / DRIFT_MODERATE) ─────────
    for result in run.feature_results.all():
        if result.status == DriftStatus.HIGH:
            raise_alert(
                "DRIFT_HIGH",
                AlertSeverity.CRITICAL,
                AlertCategory.DRIFT,
                f"High drift detected — {result.feature_name}",
                result.explanation
                or f"PSI {result.psi:.3f} exceeds the high threshold.",
                feature_name=result.feature_name,
            )
        elif result.status == DriftStatus.MODERATE:
            raise_alert(
                "DRIFT_MODERATE",
                AlertSeverity.WARNING,
                AlertCategory.DRIFT,
                f"Moderate drift detected — {result.feature_name}",
                result.explanation
                or f"PSI {result.psi:.3f} exceeds the moderate threshold.",
                feature_name=result.feature_name,
            )

    # ── performance (§9.1 PERFORMANCE_DROP_*) ─────────────────────────
    snapshot = getattr(run, "performance", None)
    if snapshot is not None and snapshot.accuracy is not None:
        from monitoring.services import reference_accuracy_for

        reference = (
            reference_accuracy_for(run.model_version) if run.model_version else None
        )
        if reference is not None:
            drop = reference - snapshot.accuracy
            if drop >= thresholds["accuracy_drop_major"]:
                raise_alert(
                    "PERFORMANCE_DROP_MAJOR",
                    AlertSeverity.CRITICAL,
                    AlertCategory.PERFORMANCE,
                    "Accuracy has fallen sharply",
                    f"Accuracy is {snapshot.accuracy:.4f}, {drop * 100:.1f} points below "
                    f"the reference of {reference:.4f}.",
                )
            elif drop >= thresholds["accuracy_drop_minor"]:
                raise_alert(
                    "PERFORMANCE_DROP_MINOR",
                    AlertSeverity.WARNING,
                    AlertCategory.PERFORMANCE,
                    "Accuracy has fallen",
                    f"Accuracy is {snapshot.accuracy:.4f}, {drop * 100:.1f} points below "
                    f"the reference of {reference:.4f}.",
                )

    # ── data quality (§9.1 QUALITY_*) ─────────────────────────────────
    quality = getattr(run, "quality", None)
    if quality is not None:
        if quality.quality_score < 50:
            raise_alert(
                "QUALITY_POOR",
                AlertSeverity.CRITICAL,
                AlertCategory.QUALITY,
                "Incoming data quality is poor",
                f"Data quality scored {quality.quality_score}/100.",
            )
        elif quality.quality_score < 70:
            raise_alert(
                "QUALITY_DEGRADED",
                AlertSeverity.WARNING,
                AlertCategory.QUALITY,
                "Incoming data quality has degraded",
                f"Data quality scored {quality.quality_score}/100.",
            )

    # ── health (§9.1 HEALTH_*) ────────────────────────────────────────
    if run.health_score is not None:
        if run.health_score < thresholds["health_critical_threshold"]:
            raise_alert(
                "HEALTH_CRITICAL",
                AlertSeverity.CRITICAL,
                AlertCategory.HEALTH,
                "Model health is critical",
                f"Health score {run.health_score}/100, below the critical threshold "
                f"of {thresholds['health_critical_threshold']}.",
            )
        elif run.health_score < thresholds["health_warning_threshold"]:
            raise_alert(
                "HEALTH_WARNING",
                AlertSeverity.WARNING,
                AlertCategory.HEALTH,
                "Model health has degraded",
                f"Health score {run.health_score}/100, below the healthy threshold "
                f"of {thresholds['health_warning_threshold']}.",
            )

    return raised


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
