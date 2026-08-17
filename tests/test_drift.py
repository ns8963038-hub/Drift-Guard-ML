"""Tests for monitoring.engine.drift.

Includes the mandatory engine tests from TRD.md §11. The most important one is
`test_large_sample_tiny_difference_is_significant_but_not_drift` — it is the
proof that the PRD §7.3 combination rule works, and the reason this project does
not simply report "p < 0.05 therefore drift".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from monitoring.engine import constants as C
from monitoring.engine import drift, profiling

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
TELCO_BASELINE = DATA / "telco_churn" / "baseline.csv"
TELCO_HOLDOUT = DATA / "telco_churn" / "holdout.csv"

requires_telco = pytest.mark.skipif(
    not TELCO_BASELINE.exists(),
    reason="run scripts/prepare_datasets.py first",
)

TH = drift.default_thresholds()


def numeric_profile(values: np.ndarray) -> dict:
    """Minimal profile entry for one numeric column."""
    edges = profiling.build_bin_edges(values)
    return {
        "type": C.NUMERIC,
        "bin_edges": edges,
        "bin_counts": profiling.bin_counts(values, edges),
        "summary": profiling.summarise_numeric(pd.Series(values)),
    }


# ──────────────────────────────────────────────────────────────────────
# PSI
# ──────────────────────────────────────────────────────────────────────


def test_psi_of_identical_distributions_is_zero():
    counts = [100, 200, 300, 250, 150]
    assert drift.population_stability_index(counts, counts) == pytest.approx(
        0.0, abs=1e-12
    )


def test_psi_grows_with_divergence():
    baseline = [500, 300, 200]
    near = [480, 310, 210]
    far = [100, 200, 700]
    assert drift.population_stability_index(
        baseline, near
    ) < drift.population_stability_index(baseline, far)


def test_psi_is_finite_when_a_bin_is_empty():
    """TRD §11 test 4 — the epsilon guard.

    Without smoothing, ln(actual / 0) is infinity and every downstream number
    becomes NaN. Empty bins are routine, not exotic.
    """
    baseline = [500, 0, 300, 200]  # empty bin in the baseline
    current = [100, 400, 300, 200]  # populated in the batch

    psi = drift.population_stability_index(baseline, current)
    assert np.isfinite(psi), "PSI must never be inf"
    assert not np.isnan(psi), "PSI must never be NaN"
    assert psi > 0


def test_psi_handles_both_sides_empty_bins():
    psi = drift.population_stability_index([0, 500, 0], [0, 0, 500])
    assert np.isfinite(psi) and psi > 0


def test_psi_rejects_mismatched_bin_counts():
    with pytest.raises(ValueError, match="matching bin counts"):
        drift.population_stability_index([1, 2, 3], [1, 2])


def test_psi_of_empty_input_is_zero():
    assert drift.population_stability_index([], []) == 0.0


# ──────────────────────────────────────────────────────────────────────
# JSD
# ──────────────────────────────────────────────────────────────────────


def test_jsd_of_identical_distributions_is_zero():
    counts = [100, 200, 300]
    assert drift.jensen_shannon_divergence(counts, counts) == pytest.approx(
        0.0, abs=1e-12
    )


def test_jsd_of_disjoint_distributions_is_one():
    """Base 2 is what makes the upper bound exactly 1.

    With natural logs it would be ln(2) ≈ 0.693 and the PRD's 0.10/0.20 bands
    would silently mean something other than what they say.
    """
    assert drift.jensen_shannon_divergence(
        [1000, 0], [0, 1000], epsilon=0.0
    ) == pytest.approx(1.0)


def test_smoothing_pulls_the_maximum_just_below_one():
    """Documents the cost of the epsilon guard.

    Smoothing moves a little mass into every empty bin, so two fully disjoint
    distributions score marginally under the theoretical 1.0. At epsilon=1e-4
    the shortfall is ~0.0015 — four orders of magnitude below the 0.20 high-drift
    band, so it can never change a verdict. Worth pinning so nobody later raises
    epsilon far enough to matter without noticing.
    """
    jsd = drift.jensen_shannon_divergence([1000, 0], [0, 1000])
    assert 0.99 < jsd < 1.0
    assert 1.0 - jsd < drift.default_thresholds()["jsd_moderate"] / 10


def test_jsd_stays_within_bounds():
    rng = np.random.default_rng(0)
    for _ in range(50):
        a = rng.integers(0, 500, size=6)
        b = rng.integers(0, 500, size=6)
        jsd = drift.jensen_shannon_divergence(a, b)
        assert 0.0 <= jsd <= 1.0


def test_jsd_is_symmetric():
    a, b = [300, 200, 500], [100, 700, 200]
    assert drift.jensen_shannon_divergence(a, b) == pytest.approx(
        drift.jensen_shannon_divergence(b, a)
    )


# ──────────────────────────────────────────────────────────────────────
# K-S test
# ──────────────────────────────────────────────────────────────────────


def test_ks_on_identical_samples_is_not_significant():
    values = np.random.default_rng(0).normal(0, 1, 2000)
    statistic, p_value = drift.ks_test(values, values.copy())
    assert statistic == pytest.approx(0.0)
    assert p_value > 0.05


def test_ks_detects_a_shifted_distribution():
    rng = np.random.default_rng(1)
    baseline = rng.normal(0, 1, 3000)
    shifted = rng.normal(2, 1, 1000)
    statistic, p_value = drift.ks_test(baseline, shifted)
    assert statistic > 0.5
    assert p_value < 0.001


def test_ks_on_constant_columns_returns_no_difference_not_nan():
    """TRD §5.2 — a zero-variance column must not poison a run."""
    constant = np.full(500, 7.0)
    statistic, p_value = drift.ks_test(constant, constant.copy())
    assert statistic == 0.0
    assert p_value == 1.0


def test_ks_on_two_different_constants_is_maximal():
    statistic, p_value = drift.ks_test(np.full(100, 1.0), np.full(100, 9.0))
    assert statistic == 1.0
    assert p_value < 0.05


def test_ks_on_empty_input_returns_no_difference():
    assert drift.ks_test(np.array([]), np.array([1.0, 2.0])) == (0.0, 1.0)


def test_ks_ignores_nans():
    rng = np.random.default_rng(2)
    clean = rng.normal(0, 1, 1000)
    with_nans = np.concatenate([clean, np.full(200, np.nan)])
    statistic, _ = drift.ks_test(clean, with_nans)
    assert statistic == pytest.approx(0.0, abs=1e-9)


def test_ks_is_capped_and_reproducible():
    """Large inputs are subsampled with a fixed seed (PRD NFR-14)."""
    rng = np.random.default_rng(3)
    big = rng.normal(0, 1, drift.MAX_TEST_SAMPLE + 20_000)
    other = rng.normal(0.5, 1, 5_000)
    assert drift.ks_test(big, other) == drift.ks_test(big, other)


# ──────────────────────────────────────────────────────────────────────
# Chi-Square
# ──────────────────────────────────────────────────────────────────────


def test_chi_square_on_identical_proportions_is_not_significant():
    counts = {"a": 500, "b": 300, "c": 200}
    _, p_value = drift.chi_square_test(counts, dict(counts))
    assert p_value > 0.05


def test_chi_square_detects_a_proportion_shift():
    baseline = {"Month-to-month": 2300, "One year": 900, "Two year": 1000}
    current = {"Month-to-month": 900, "One year": 60, "Two year": 40}
    statistic, p_value = drift.chi_square_test(baseline, current)
    assert statistic > 0
    assert p_value < 0.001


def test_chi_square_pools_sparse_categories():
    """Rare categories violate the expected-count assumption and are pooled."""
    baseline = {"a": 1000, "b": 900, "rare1": 1, "rare2": 1, "rare3": 1}
    current = {"a": 500, "b": 450, "rare1": 1}
    statistic, p_value = drift.chi_square_test(baseline, current)
    assert np.isfinite(statistic) and np.isfinite(p_value)
    assert 0.0 <= p_value <= 1.0


def test_chi_square_with_one_category_is_undefined_not_an_error():
    assert drift.chi_square_test({"only": 500}, {"only": 300}) == (0.0, 1.0)


def test_chi_square_with_an_empty_side_is_undefined_not_an_error():
    assert drift.chi_square_test({"a": 10, "b": 10}, {}) == (0.0, 1.0)


# ──────────────────────────────────────────────────────────────────────
# classify_feature — the PRD §7.3 combination rule
# ──────────────────────────────────────────────────────────────────────


def test_no_magnitude_means_no_drift_however_significant():
    assert (
        drift.classify_feature(
            psi=0.01, jsd=0.01, p_value=1e-12, n_baseline=5000, n_current=5000
        )
        == C.NONE
    )


def test_moderate_magnitude_confirmed_by_significance():
    assert (
        drift.classify_feature(
            psi=0.15, jsd=0.05, p_value=0.001, n_baseline=500, n_current=500
        )
        == C.MODERATE
    )


def test_high_magnitude_confirmed_by_significance():
    assert (
        drift.classify_feature(
            psi=0.40, jsd=0.05, p_value=0.001, n_baseline=500, n_current=500
        )
        == C.HIGH
    )


def test_worse_of_psi_and_jsd_decides():
    """JSD alone can carry the band even when PSI is quiet."""
    assert (
        drift.classify_feature(
            psi=0.02, jsd=0.30, p_value=0.001, n_baseline=500, n_current=500
        )
        == C.HIGH
    )


def test_unconfirmed_magnitude_is_downgraded_not_dropped():
    """The small-sample guard: large shift, but chance cannot be ruled out."""
    assert (
        drift.classify_feature(
            psi=0.40, jsd=0.05, p_value=0.30, n_baseline=50, n_current=50
        )
        == C.MODERATE
    )
    assert (
        drift.classify_feature(
            psi=0.15, jsd=0.05, p_value=0.30, n_baseline=50, n_current=50
        )
        == C.NONE
    )


def test_insufficient_data_beats_everything():
    """TRD §11 test 6.

    Under the minimum sample size the answer is 'we could not look', which is
    not the same as 'we looked and found nothing'.
    """
    assert (
        drift.classify_feature(
            psi=9.9, jsd=0.9, p_value=1e-9, n_baseline=29, n_current=5000
        )
        == C.INSUFFICIENT_DATA
    )
    assert (
        drift.classify_feature(
            psi=9.9, jsd=0.9, p_value=1e-9, n_baseline=5000, n_current=29
        )
        == C.INSUFFICIENT_DATA
    )
    assert (
        drift.classify_feature(
            psi=0.0, jsd=0.0, p_value=1.0, n_baseline=30, n_current=30
        )
        == C.NONE
    )


def test_band_boundaries_are_inclusive_at_the_lower_edge():
    assert drift.band(0.0999, 0.10, 0.25) == C.NONE
    assert drift.band(0.10, 0.10, 0.25) == C.MODERATE
    assert drift.band(0.25, 0.10, 0.25) == C.MODERATE
    assert drift.band(0.2501, 0.10, 0.25) == C.HIGH


# ──────────────────────────────────────────────────────────────────────
# The mandatory end-to-end distribution tests (TRD §11)
# ──────────────────────────────────────────────────────────────────────


def test_identical_data_produces_no_drift():
    """TRD §11 test 1."""
    rng = np.random.default_rng(10)
    values = rng.normal(50, 10, 4000)
    entry = numeric_profile(values)

    result = drift._analyse_numeric("feature", entry, values, pd.Series(values), TH)

    assert result["psi"] == pytest.approx(0.0, abs=1e-9)
    assert result["jsd"] == pytest.approx(0.0, abs=1e-9)
    assert result["status"] == C.NONE


def test_two_sigma_mean_shift_is_high_drift():
    """TRD §11 test 2 — the headline case."""
    rng = np.random.default_rng(11)
    baseline = rng.normal(50, 10, 5000)
    entry = numeric_profile(baseline)

    shifted = rng.normal(50 + 2 * 10, 10, 1000)  # exactly +2σ
    result = drift._analyse_numeric(
        "MonthlyCharges", entry, baseline, pd.Series(shifted), TH
    )

    assert result["status"] == C.HIGH
    assert result["psi"] > TH["psi_high"]
    assert result["p_value"] < 0.05


def test_categorical_proportion_flip_is_high_drift():
    """TRD §11 test 3."""
    baseline_counts = {"Month-to-month": 2200, "One year": 1000, "Two year": 800}
    entry = {
        "type": C.CATEGORICAL,
        "categories": baseline_counts,
        "summary": {"count": 4000, "missing": 0, "n_unique": 3},
    }

    batch = pd.Series(["Month-to-month"] * 900 + ["One year"] * 70 + ["Two year"] * 30)
    result = drift._analyse_categorical("Contract", entry, batch, TH)

    assert result["status"] == C.HIGH
    assert result["psi"] > TH["psi_high"]
    assert result["p_value"] < 0.05
    assert result["test_name"] == C.CHI2


def test_unseen_category_is_handled_and_reported():
    """TRD §11 test 5.

    A category the baseline never saw must not crash the run, must push PSI up,
    and must be reported so the data-quality module can flag it.
    """
    entry = {
        "type": C.CATEGORICAL,
        "categories": {"Card": 2000, "Bank": 1500, "Cheque": 500},
        "summary": {"count": 4000, "missing": 0, "n_unique": 3},
    }
    batch = pd.Series(["Card"] * 300 + ["Bank"] * 200 + ["Crypto"] * 500)

    result = drift._analyse_categorical("PaymentMethod", entry, batch, TH)

    assert "Crypto" in result["unseen_categories"]
    assert np.isfinite(result["psi"]) and result["psi"] > 0
    assert result["status"] in (C.MODERATE, C.HIGH)


def test_large_sample_tiny_difference_is_significant_but_not_drift():
    """TRD §11 test 7 — the proof that PRD §7.3 earns its place.

    Two samples of 50,000 differing by 0.05σ. The K-S test detects it easily,
    because with enough data any difference becomes statistically significant.
    But a 0.05σ shift is operationally meaningless, PSI stays far below the
    moderate band, and the correct answer is NONE.

    A naive "p < 0.05 therefore drift" implementation reports HIGH here and
    would fire alerts on every batch forever.
    """
    rng = np.random.default_rng(12)
    baseline = rng.normal(0, 1, 50_000)
    entry = numeric_profile(baseline)

    barely_shifted = rng.normal(0.05, 1, 50_000)
    result = drift._analyse_numeric(
        "feature", entry, baseline, pd.Series(barely_shifted), TH
    )

    assert result["p_value"] < 0.05, "K-S should detect it at this sample size"
    assert result["psi"] < TH["psi_moderate"], "but the magnitude is trivial"
    assert result["status"] == C.NONE, "so the verdict must be no drift"


def test_scores_are_reproducible():
    """TRD §11 test 9 — the same batch scored twice gives identical numbers."""
    rng = np.random.default_rng(13)
    baseline = rng.normal(20, 5, 4000)
    entry = numeric_profile(baseline)
    batch = pd.Series(rng.normal(24, 6, 800))

    first = drift._analyse_numeric("f", entry, baseline, batch, TH)
    second = drift._analyse_numeric("f", entry, baseline, batch, TH)

    for key in ("psi", "jsd", "test_statistic", "p_value", "status"):
        assert first[key] == second[key], key


# ──────────────────────────────────────────────────────────────────────
# rollup
# ──────────────────────────────────────────────────────────────────────


def _results(*statuses: str) -> list[dict]:
    return [{"status": s, "psi": 0.0} for s in statuses]


def test_rollup_none_when_all_clean():
    assert drift.rollup(_results(C.NONE, C.NONE, C.NONE)) == C.NONE


def test_rollup_moderate_on_a_single_moderate_feature():
    assert (
        drift.rollup(_results(C.NONE, C.MODERATE, C.NONE, C.NONE, C.NONE)) == C.MODERATE
    )


def test_rollup_high_on_any_single_high_feature():
    assert drift.rollup(_results(*([C.NONE] * 19), C.HIGH)) == C.HIGH


def test_rollup_high_when_enough_features_are_moderate():
    """Many features drifting together is a distribution shift, even with no
    individual feature looking alarming. 3 of 10 hits the 30% default."""
    assert drift.rollup(_results(*([C.MODERATE] * 3), *([C.NONE] * 7))) == C.HIGH
    assert drift.rollup(_results(*([C.MODERATE] * 2), *([C.NONE] * 8))) == C.MODERATE


def test_rollup_ignores_insufficient_data_in_both_numerator_and_denominator():
    """2 moderate out of 4 evaluated is 50% -> HIGH, despite 6 unusable columns."""
    results = _results(
        C.MODERATE, C.MODERATE, C.NONE, C.NONE, *([C.INSUFFICIENT_DATA] * 6)
    )
    assert drift.rollup(results) == C.HIGH


def test_rollup_of_nothing_evaluable_is_none():
    assert drift.rollup(_results(C.INSUFFICIENT_DATA, C.INSUFFICIENT_DATA)) == C.NONE
    assert drift.rollup([]) == C.NONE


# ──────────────────────────────────────────────────────────────────────
# analyse_features — integration on real data
# ──────────────────────────────────────────────────────────────────────


@requires_telco
def test_holdout_against_baseline_shows_no_drift():
    """The strongest sanity check available.

    The holdout is a random split of the same population as the baseline, so a
    correct detector must report essentially nothing. If this fails, the engine
    is inventing drift and every other result is worthless.
    """
    baseline = pd.read_csv(TELCO_BASELINE)
    holdout = pd.read_csv(TELCO_HOLDOUT)

    schema = profiling.infer_schema(baseline, "Churn")
    profile = profiling.build_profile(baseline, schema)

    results = drift.analyse_features(profile, baseline, holdout, schema)

    assert len(results) == 19
    drifted = [r for r in results if r["status"] in (C.MODERATE, C.HIGH)]
    assert (
        not drifted
    ), f"false positives on an identical population: {[d['feature_name'] for d in drifted]}"
    assert drift.rollup(results) == C.NONE


@requires_telco
def test_injected_shift_is_detected_on_real_data():
    """Same holdout, but with MonthlyCharges shifted by 2σ and Contract flipped."""
    baseline = pd.read_csv(TELCO_BASELINE)
    holdout = pd.read_csv(TELCO_HOLDOUT).copy()

    schema = profiling.infer_schema(baseline, "Churn")
    profile = profiling.build_profile(baseline, schema)

    holdout["MonthlyCharges"] = (
        holdout["MonthlyCharges"] + 2 * baseline["MonthlyCharges"].std()
    )
    rng = np.random.default_rng(14)
    holdout["Contract"] = rng.choice(
        ["Month-to-month", "One year", "Two year"],
        size=len(holdout),
        p=[0.90, 0.07, 0.03],
    )

    results = drift.analyse_features(profile, baseline, holdout, schema)
    by_name = {r["feature_name"]: r for r in results}

    assert by_name["MonthlyCharges"]["status"] == C.HIGH
    assert by_name["Contract"]["status"] == C.HIGH
    assert by_name["tenure"]["status"] == C.NONE, "untouched column must stay clean"
    assert drift.rollup(results) == C.HIGH

    # Worst-first ordering (PRD FR-08.2)
    assert results[0]["status"] == C.HIGH


@requires_telco
def test_excluded_columns_are_not_analysed():
    baseline = pd.read_csv(TELCO_BASELINE)
    holdout = pd.read_csv(TELCO_HOLDOUT)

    schema = profiling.infer_schema(baseline, "Churn")
    profile = profiling.build_profile(baseline, schema)
    results = drift.analyse_features(profile, baseline, holdout, schema)

    names = {r["feature_name"] for r in results}
    assert "customerID" not in names
    assert "Churn" not in names


@requires_telco
def test_tiny_batch_is_reported_as_insufficient_data():
    baseline = pd.read_csv(TELCO_BASELINE)
    schema = profiling.infer_schema(baseline, "Churn")
    profile = profiling.build_profile(baseline, schema)

    tiny = pd.read_csv(TELCO_HOLDOUT).head(5)
    results = drift.analyse_features(profile, baseline, tiny, schema)

    assert all(r["status"] == C.INSUFFICIENT_DATA for r in results)
    assert drift.rollup(results) == C.NONE
