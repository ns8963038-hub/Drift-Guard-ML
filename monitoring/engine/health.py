"""Model health score — PRD FR-09 and §8.

One integer, 0–100, combining four components:

    performance   how far accuracy has fallen below its reference
    drift         how many features have drifted, weighted by severity
    quality       the data quality score for this batch
    stability     how far the prediction mix has moved from the baseline's

The score is never presented alone. Every result carries the component
breakdown and the weight set used, because "your model is 74" is not actionable
and "74: performance 82, drift 61, quality 88, stability 93" is (FR-09.4).

**Weights are redistributed when labels are absent** (§8.3). A batch with no
ground truth cannot say anything about accuracy, so scoring performance as 0
would punish a healthy model for the entirely normal situation of ground truth
not having arrived yet. Instead the performance weight is removed and the
remaining three components carry the score, with the UI stating which weighting
was applied (FR-09.5).

Pure Python. Imports no Django (BACKEND_FLOW.md §1).
"""

from __future__ import annotations

from typing import Any

from . import drift

# §8.3 — the two weight sets.
WEIGHTS_WITH_LABELS = {
    "performance": 40.0,
    "drift": 30.0,
    "quality": 20.0,
    "stability": 10.0,
}
WEIGHTS_WITHOUT_LABELS = {
    "performance": 0.0,
    "drift": 50.0,
    "quality": 35.0,
    "stability": 15.0,
}

# §8.4 — bands.
HEALTHY_MINIMUM = 80
WARNING_MINIMUM = 60

HEALTHY = "HEALTHY"
WARNING = "WARNING"
CRITICAL = "CRITICAL"

# §8.1 — a 1-point accuracy drop costs 2 points of the performance component,
# so a 50-point collapse takes it to zero.
ACCURACY_DROP_MULTIPLIER = 200.0

# §8.2 — severity weights for drifted features.
HIGH_FEATURE_PENALTY = 15.0
MODERATE_FEATURE_PENALTY = 6.0

# §8.2 — a fully diverged prediction mix (JSD 1.0) takes stability to zero.
STABILITY_MULTIPLIER = 200.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(min(max(value, low), high))


def performance_component(
    current_accuracy: float | None, reference_accuracy: float | None
) -> float | None:
    """§8.1. Returns None when there is nothing to measure.

    ``reference_accuracy`` is the version's recorded training accuracy, or the
    accuracy of its first labelled run. On that very first run there is no
    reference yet, so the component scores 100 — the run establishes the
    reference rather than being judged against a baseline that does not exist.

    Improvement is not rewarded. Beating the reference clamps at 100 rather than
    inflating the score, because the score measures degradation.
    """
    if current_accuracy is None:
        return None
    if reference_accuracy is None:
        return 100.0

    drop = max(0.0, reference_accuracy - current_accuracy)
    return _clamp(100.0 - drop * ACCURACY_DROP_MULTIPLIER)


def drift_component(high_count: int, moderate_count: int) -> float:
    """§8.2. Severity-weighted count of drifted features.

    A single HIGH feature costs 15; a MODERATE costs 6. Seven high-drift
    features take the component to zero, which is the intended behaviour —
    beyond that point the model is comprehensively broken and further precision
    is meaningless.
    """
    penalty = (
        HIGH_FEATURE_PENALTY * high_count + MODERATE_FEATURE_PENALTY * moderate_count
    )
    return _clamp(100.0 - penalty)


def stability_component(
    baseline_distribution: dict[str, float] | None,
    current_distribution: dict[str, float] | None,
) -> float:
    """§8.2. How far the prediction mix has moved.

    This is the only performance-like signal available without labels, which is
    why it carries more weight in the unlabelled weighting. A model that used to
    predict 27% churn and now predicts 61% has changed behaviour, whether or not
    anyone can yet say if it is right.

    Returns 100 when there is no baseline to compare against — the same "no
    reference yet" reasoning as the performance component.
    """
    if not baseline_distribution or not current_distribution:
        return 100.0

    classes = sorted(set(baseline_distribution) | set(current_distribution))
    baseline_vector = [float(baseline_distribution.get(c, 0.0)) for c in classes]
    current_vector = [float(current_distribution.get(c, 0.0)) for c in classes]

    divergence = drift.jensen_shannon_divergence(baseline_vector, current_vector)
    return _clamp(100.0 - STABILITY_MULTIPLIER * divergence)


# §8.4a — the coherence cap. A run whose overall drift status is HIGH can never
# be reported as HEALTHY, whatever the arithmetic says.
HIGH_DRIFT_SCORE_CEILING = 79


def band(score: int | float) -> str:
    """§8.4."""
    if score >= HEALTHY_MINIMUM:
        return HEALTHY
    if score >= WARNING_MINIMUM:
        return WARNING
    return CRITICAL


def apply_coherence_cap(score: int, overall_drift_status: str | None) -> int:
    """§8.4a. Stop the score contradicting the rest of the run.

    The weighted formula can return a HEALTHY score while several features sit
    at HIGH drift, because drift carries only 30 of the 100 weight. Observed in
    practice: 3 of 19 features at HIGH drift with accuracy down 4 points scored
    81 — so the run detail page would show a red drift badge beside a green
    health badge, and an URGENT retraining recommendation beside "HEALTHY".

    HIGH drift is a CRITICAL-tier retraining trigger (§10). A score that calls
    that healthy is not a summary, it is a contradiction — and the health score
    exists precisely so one glance is enough (goal G3).

    MODERATE drift is deliberately not capped. It is a warning worth weighing
    against the other components, not an override.
    """
    if overall_drift_status == "HIGH":
        return min(score, HIGH_DRIFT_SCORE_CEILING)
    return score


def compute(
    *,
    current_accuracy: float | None,
    reference_accuracy: float | None,
    high_count: int,
    moderate_count: int,
    quality_score: float,
    baseline_prediction_distribution: dict[str, float] | None,
    current_prediction_distribution: dict[str, float] | None,
    labels_available: bool,
    overall_drift_status: str | None = None,
) -> dict[str, Any]:
    """Compute the health score and its full breakdown.

    Keyword-only on purpose: eight positional arguments of similar type is a
    silent-bug generator, and swapping ``high_count`` with ``moderate_count``
    would produce a plausible-looking wrong answer.
    """
    weights = dict(WEIGHTS_WITH_LABELS if labels_available else WEIGHTS_WITHOUT_LABELS)

    components: dict[str, float | None] = {
        "performance": performance_component(current_accuracy, reference_accuracy),
        "drift": drift_component(high_count, moderate_count),
        "quality": _clamp(float(quality_score)),
        "stability": stability_component(
            baseline_prediction_distribution, current_prediction_distribution
        ),
    }

    # Defensive: if labels were claimed but no accuracy arrived, fall back to the
    # unlabelled weighting rather than silently scoring performance as zero.
    if components["performance"] is None:
        weights = dict(WEIGHTS_WITHOUT_LABELS)
        labels_available = False

    active = {name: weight for name, weight in weights.items() if weight > 0}
    total_weight = sum(active.values())

    weighted = sum(components[name] * weight for name, weight in active.items())
    raw_score = int(round(weighted / total_weight)) if total_weight else 0
    score = apply_coherence_cap(raw_score, overall_drift_status)

    return {
        "score": score,
        "raw_score": raw_score,
        "capped": score != raw_score,
        "band": band(score),
        "components": {
            name: (None if value is None else round(float(value), 2))
            for name, value in components.items()
        },
        "weights": weights,
        "weighting": "with_labels" if labels_available else "without_labels",
        "labels_available": labels_available,
    }
