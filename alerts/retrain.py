from django.db import transaction
from alerts.models import RetrainRecommendation
from alerts.services import resolve_thresholds
from core.constants import RetrainSeverity, RetrainStatus


@transaction.atomic
def evaluate_retrain(run):
    """
    Contract C16: Evaluates retraining recommendation triggers (PRD §10).
    Creates or updates an OPEN RetrainRecommendation row.
    """
    if not run or not hasattr(run, "ml_model"):
        return None

    ml_model = run.ml_model
    version = getattr(run, "model_version", None) or ml_model.active_version
    if not version:
        return None

    thresholds = resolve_thresholds(ml_model)
    triggers = []
    severity = RetrainSeverity.ADVISED

    # Check health score
    health_score = getattr(run, "health_score", 100)
    if (
        health_score is not None
        and health_score < thresholds["health_critical_threshold"]
    ):
        triggers.append(
            f"Health score ({health_score}) fell below critical threshold ({thresholds['health_critical_threshold']})."
        )
        severity = RetrainSeverity.URGENT

    # Check accuracy drop
    accuracy_drop = getattr(run, "accuracy_drop", None)
    if (
        accuracy_drop is not None
        and accuracy_drop > thresholds["accuracy_drop_threshold"]
    ):
        triggers.append(
            f"Model accuracy dropped by {accuracy_drop:.2%} (threshold: {thresholds['accuracy_drop_threshold']:.2%})."
        )
        if accuracy_drop > 0.15:
            severity = RetrainSeverity.URGENT

    # Check high drift feature count
    high_drift_count = 0
    if hasattr(run, "feature_drift_results"):
        high_drift_count = run.feature_drift_results.filter(drift_status="HIGH").count()
        if high_drift_count >= 3:
            triggers.append(f"{high_drift_count} features exhibit HIGH data drift.")
            severity = RetrainSeverity.URGENT

    if not triggers:
        return None

    # Get or update open recommendation
    rec, created = RetrainRecommendation.objects.get_or_create(
        ml_model=ml_model,
        version=version,
        status=RetrainStatus.OPEN,
        defaults={"severity": severity, "triggers": triggers},
    )

    if not created:
        rec.severity = severity
        rec.triggers = triggers
        rec.save(update_fields=["severity", "triggers"])

    return rec
