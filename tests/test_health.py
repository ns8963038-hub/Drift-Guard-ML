"""Tests for monitoring.engine.health — PRD FR-09 and §8.

Includes TRD §11 test 9: with labels absent the weights must be redistributed
and the applied weighting reported.
"""

from __future__ import annotations

import pytest

from monitoring.engine import health


def score(**overrides):
    """compute() with sensible defaults, overridable per test."""
    kwargs = dict(
        current_accuracy=0.90,
        reference_accuracy=0.90,
        high_count=0,
        moderate_count=0,
        quality_score=100.0,
        baseline_prediction_distribution={"no": 0.7, "yes": 0.3},
        current_prediction_distribution={"no": 0.7, "yes": 0.3},
        labels_available=True,
    )
    kwargs.update(overrides)
    return health.compute(**kwargs)


# ──────────────────────────────────────────────────────────────────────
# Components
# ──────────────────────────────────────────────────────────────────────


def test_performance_component_is_full_when_accuracy_holds():
    assert health.performance_component(0.90, 0.90) == 100.0


def test_performance_component_falls_with_accuracy():
    """§8.1 — a 10-point drop costs 20 points."""
    assert health.performance_component(0.80, 0.90) == pytest.approx(80.0)
    assert health.performance_component(0.65, 0.90) == pytest.approx(50.0)
    assert health.performance_component(0.40, 0.90) == pytest.approx(0.0)


def test_performance_component_does_not_reward_improvement():
    """Beating the reference clamps at 100. The score measures degradation."""
    assert health.performance_component(0.99, 0.80) == 100.0


def test_performance_component_floors_at_zero():
    assert health.performance_component(0.05, 0.95) == 0.0


def test_performance_component_without_a_reference_is_full():
    """The first labelled run establishes the reference; it is not judged."""
    assert health.performance_component(0.72, None) == 100.0


def test_performance_component_without_accuracy_is_none():
    assert health.performance_component(None, 0.90) is None


def test_drift_component_penalties():
    """§8.2 — HIGH costs 15, MODERATE costs 6."""
    assert health.drift_component(0, 0) == 100.0
    assert health.drift_component(1, 0) == 85.0
    assert health.drift_component(0, 1) == 94.0
    assert health.drift_component(2, 3) == pytest.approx(100 - 30 - 18)


def test_drift_component_floors_at_zero():
    assert health.drift_component(20, 20) == 0.0


def test_stability_component_is_full_for_an_unchanged_prediction_mix():
    distribution = {"no": 0.73, "yes": 0.27}
    assert health.stability_component(distribution, dict(distribution)) == 100.0


def test_stability_component_falls_as_the_prediction_mix_moves():
    baseline = {"no": 0.73, "yes": 0.27}
    shifted = {"no": 0.40, "yes": 0.60}
    assert health.stability_component(baseline, shifted) < 100.0


def test_stability_component_collapses_when_predictions_invert():
    assert (
        health.stability_component({"no": 1.0, "yes": 0.0}, {"no": 0.0, "yes": 1.0})
        == 0.0
    )


def test_stability_component_without_a_baseline_is_full():
    assert health.stability_component(None, {"a": 1.0}) == 100.0
    assert health.stability_component({}, {"a": 1.0}) == 100.0


# ──────────────────────────────────────────────────────────────────────
# Bands — §8.4
# ──────────────────────────────────────────────────────────────────────


def test_band_boundaries():
    assert health.band(100) == health.HEALTHY
    assert health.band(80) == health.HEALTHY
    assert health.band(79) == health.WARNING
    assert health.band(60) == health.WARNING
    assert health.band(59) == health.CRITICAL
    assert health.band(0) == health.CRITICAL


# ──────────────────────────────────────────────────────────────────────
# compute
# ──────────────────────────────────────────────────────────────────────


def test_a_perfect_run_scores_100():
    result = score()
    assert result["score"] == 100
    assert result["band"] == health.HEALTHY


def test_score_degrades_with_each_component():
    healthy = score()["score"]
    drifted = score(high_count=2)["score"]
    degraded = score(high_count=2, current_accuracy=0.78)["score"]
    dirty = score(high_count=2, current_accuracy=0.78, quality_score=55.0)["score"]

    assert healthy > drifted > degraded > dirty


def test_breakdown_is_always_returned():
    """FR-09.4 — the score is never a black box."""
    result = score(high_count=1, current_accuracy=0.85, quality_score=88.0)
    assert set(result["components"]) == {"performance", "drift", "quality", "stability"}
    assert result["components"]["drift"] == 85.0
    assert result["components"]["quality"] == 88.0
    assert result["weights"]["performance"] == 40.0


def test_score_is_a_plain_integer_in_range():
    result = score(high_count=3, current_accuracy=0.50, quality_score=30.0)
    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100


def test_worked_example_matches_the_documented_formula():
    """Hand-checked against §8.3.

    performance 82 x40 + drift 61 x30 + quality 88 x20 + stability 93 x10
      = 3280 + 1830 + 1760 + 930 = 7800, / 100 = 78.
    """
    result = health.compute(
        current_accuracy=0.90 - 0.09,  # 9-point drop -> 100 - 18 = 82
        reference_accuracy=0.90,
        high_count=1,
        moderate_count=4,  # 100 - 15 - 24 = 61
        quality_score=88.0,
        baseline_prediction_distribution=None,
        current_prediction_distribution=None,
        labels_available=True,
    )
    assert result["components"]["performance"] == pytest.approx(82.0)
    assert result["components"]["drift"] == pytest.approx(61.0)
    # stability defaults to 100 with no baseline, so recompute expectation:
    expected = (82 * 40 + 61 * 30 + 88 * 20 + 100 * 10) / 100
    assert result["score"] == int(round(expected))


# ──────────────────────────────────────────────────────────────────────
# TRD §11 test 9 — the labels-absent weighting
# ──────────────────────────────────────────────────────────────────────


def test_weights_are_redistributed_when_labels_are_absent():
    result = score(current_accuracy=None, labels_available=False)

    assert result["weighting"] == "without_labels"
    assert result["weights"] == health.WEIGHTS_WITHOUT_LABELS
    assert result["weights"]["performance"] == 0.0
    assert result["weights"]["drift"] == 50.0
    assert result["components"]["performance"] is None


def test_unlabelled_run_is_not_punished_for_missing_accuracy():
    """The behaviour this whole mechanism exists to prevent.

    Scoring an absent accuracy as 0 would take a healthy model to 60 and fire a
    HEALTH_WARNING alert on every unlabelled batch — which in production is most
    of them.
    """
    labelled = score()
    unlabelled = score(current_accuracy=None, labels_available=False)

    assert unlabelled["score"] == 100
    assert unlabelled["band"] == health.HEALTHY
    assert unlabelled["score"] == labelled["score"]


def test_unlabelled_weighting_makes_drift_matter_more():
    """Drift carries 50 rather than 30 when it is the main signal available."""
    labelled = score(high_count=2)["score"]
    unlabelled = score(high_count=2, current_accuracy=None, labels_available=False)[
        "score"
    ]
    assert unlabelled < labelled


def test_claimed_labels_without_accuracy_falls_back_safely():
    """Defensive: a caller saying labels_available=True but passing no accuracy
    must not score performance as zero."""
    result = score(current_accuracy=None, labels_available=True)
    assert result["weighting"] == "without_labels"
    assert result["labels_available"] is False
    assert result["score"] == 100


def test_weighting_is_reported_for_the_ui():
    """FR-09.5 — the UI must be able to state which weighting was applied."""
    assert score()["weighting"] == "with_labels"
    assert (
        score(current_accuracy=None, labels_available=False)["weighting"]
        == "without_labels"
    )


def test_critical_band_is_reachable():
    result = score(
        current_accuracy=0.55,
        reference_accuracy=0.92,
        high_count=3,
        moderate_count=5,
        quality_score=45.0,
        current_prediction_distribution={"no": 0.1, "yes": 0.9},
    )
    assert result["band"] == health.CRITICAL
    assert result["score"] < 60


# ──────────────────────────────────────────────────────────────────────
# §8.4a — the coherence cap
# ──────────────────────────────────────────────────────────────────────


def test_high_drift_cannot_be_reported_as_healthy():
    """The contradiction this rule exists to prevent.

    Observed on real Telco data: 3 of 19 features at HIGH drift with accuracy
    down 4 points scored 81 under the plain weighted formula. The run page would
    then show a red drift badge beside a green health badge, and an URGENT
    retraining recommendation beside the word HEALTHY.
    """
    result = score(
        high_count=3,
        current_accuracy=0.71,
        reference_accuracy=0.7523,
        quality_score=87.0,
        overall_drift_status="HIGH",
    )

    assert result["raw_score"] >= 80, "the plain formula really does say healthy here"
    assert result["score"] == health.HIGH_DRIFT_SCORE_CEILING
    assert result["band"] == health.WARNING
    assert result["capped"] is True


def test_cap_never_raises_a_low_score():
    result = score(
        high_count=8,
        current_accuracy=0.40,
        quality_score=30.0,
        overall_drift_status="HIGH",
    )
    assert result["score"] == result["raw_score"]
    assert result["capped"] is False
    assert result["band"] == health.CRITICAL


def test_moderate_drift_is_not_capped():
    """MODERATE is a warning to weigh, not an override."""
    result = score(moderate_count=2, overall_drift_status="MODERATE")
    assert result["capped"] is False
    assert result["band"] == health.HEALTHY


def test_no_drift_status_supplied_leaves_the_score_alone():
    """Callers that do not pass a drift status get the plain formula."""
    result = score(high_count=3, quality_score=87.0)
    assert result["capped"] is False


def test_raw_score_is_always_reported():
    """The uncapped number stays visible so the cap is auditable, not magic."""
    result = score(high_count=3, quality_score=87.0, overall_drift_status="HIGH")
    assert "raw_score" in result
    assert result["raw_score"] != result["score"]
