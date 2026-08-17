"""Retraining recommendations — PRD FR-10 and §10.

The platform **never retrains anything**. It writes an advisory record naming
every trigger that fired, with the measured value against its threshold, and
stops there (FR-10.6).
"""

from django.db import transaction

from alerts.models import RetrainRecommendation
from alerts.services import create_or_update_alert, resolve_thresholds
from core.constants import (
    AlertCategory,
    AlertSeverity,
    DriftStatus,
    RetrainSeverity,
    RetrainStatus,
)

# §10 defaults
MODERATE_FEATURE_COUNT = 3
CONSECUTIVE_RUNS = 2


@transaction.atomic
def evaluate_retrain(run):
    """Contract C16. Returns the open recommendation, or None if nothing fired.

    At most one recommendation is OPEN per model at a time (FR-10.5) — further
    triggers update it rather than stacking a second one, so the screen shows
    the current situation instead of a pile of near-duplicates.
    """
    if run is None or run.model_version is None:
        return None

    ml_model = run.ml_model
    thresholds = resolve_thresholds(ml_model)

    triggers = []
    critical_tier = False

    # ── overall drift is HIGH — CRITICAL tier ─────────────────────────
    if run.overall_drift_status == DriftStatus.HIGH:
        triggers.append(
            {
                "trigger": "Overall drift status is HIGH",
                "measured": f"{run.features_high} feature(s) at high drift",
                "threshold": "any feature at high drift",
            }
        )
        critical_tier = True

    # ── enough features moderate-or-worse — ADVISED tier ──────────────
    drifted = run.features_high + run.features_moderate
    if drifted >= MODERATE_FEATURE_COUNT:
        triggers.append(
            {
                "trigger": "Several features have drifted",
                "measured": f"{drifted} features at moderate drift or worse",
                "threshold": f"{MODERATE_FEATURE_COUNT} or more",
            }
        )

    # ── accuracy below reference — CRITICAL tier ──────────────────────
    snapshot = getattr(run, "performance", None)
    if snapshot is not None and snapshot.accuracy is not None:
        from monitoring.services import reference_accuracy_for

        reference = reference_accuracy_for(run.model_version)
        if reference is not None:
            drop = reference - snapshot.accuracy
            if drop >= thresholds["accuracy_drop_minor"]:
                triggers.append(
                    {
                        "trigger": "Accuracy has fallen below its reference",
                        "measured": f"{snapshot.accuracy:.4f} ({drop * 100:.1f} points below {reference:.4f})",
                        "threshold": f"{thresholds['accuracy_drop_minor'] * 100:.0f} point drop",
                    }
                )
                critical_tier = True

    # ── health critical for K consecutive runs — CRITICAL tier ────────
    recent = list(
        ml_model.runs.filter(health_score__isnull=False)
        .order_by("-created_at")
        .values_list("health_score", flat=True)[:CONSECUTIVE_RUNS]
    )
    critical_threshold = thresholds["health_critical_threshold"]
    if len(recent) == CONSECUTIVE_RUNS and all(s < critical_threshold for s in recent):
        triggers.append(
            {
                "trigger": "Health score has stayed critical",
                "measured": f"{CONSECUTIVE_RUNS} consecutive runs below {critical_threshold} "
                f"(latest {recent[0]})",
                "threshold": f"below {critical_threshold} for {CONSECUTIVE_RUNS} runs",
            }
        )
        critical_tier = True

    # ── quality poor for K consecutive runs — ADVISED tier ────────────
    recent_quality = list(
        ml_model.runs.filter(quality__isnull=False)
        .order_by("-created_at")
        .values_list("quality__quality_score", flat=True)[:CONSECUTIVE_RUNS]
    )
    if len(recent_quality) == CONSECUTIVE_RUNS and all(q < 50 for q in recent_quality):
        triggers.append(
            {
                "trigger": "Incoming data quality has stayed poor",
                "measured": f"{CONSECUTIVE_RUNS} consecutive runs below 50 "
                f"(latest {recent_quality[0]})",
                "threshold": f"below 50 for {CONSECUTIVE_RUNS} runs",
            }
        )

    if not triggers:
        return None

    severity = (
        RetrainSeverity.URGENT
        if critical_tier or len(triggers) >= 2
        else RetrainSeverity.ADVISED
    )
    message = _compose_message(ml_model, triggers)

    existing = RetrainRecommendation.objects.filter(
        ml_model=ml_model, status=RetrainStatus.OPEN
    ).first()

    if existing is not None:
        existing.severity = severity
        existing.triggers = triggers
        existing.message = message
        existing.run = run
        existing.version = run.model_version
        existing.save(
            update_fields=["severity", "triggers", "message", "run", "version"]
        )
        return existing

    recommendation = RetrainRecommendation.objects.create(
        ml_model=ml_model,
        version=run.model_version,
        run=run,
        severity=severity,
        triggers=triggers,
        message=message,
        status=RetrainStatus.OPEN,
    )

    create_or_update_alert(
        ml_model=ml_model,
        category=AlertCategory.RETRAIN,
        severity=AlertSeverity.CRITICAL,
        headline=f"Retraining recommended for {ml_model.name}",
        message=message,
        run_id=run.pk,
        rule_code="RETRAIN_RECOMMENDED",
    )
    return recommendation


def _compose_message(ml_model, triggers):
    """FR-10.2 — name every trigger with its measured value and threshold."""
    lines = [f"Retraining is recommended for {ml_model.name}."]
    for item in triggers:
        lines.append(
            f"  · {item['trigger']}: {item['measured']} (threshold: {item['threshold']})"
        )
    lines.append("This is advisory only — the platform does not retrain models.")
    return "\n".join(lines)
