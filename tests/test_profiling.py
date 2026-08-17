"""Tests for monitoring.engine.profiling.

Covers the Phase 3 acceptance criteria from IMPLEMENTATION_PLAN.md, plus the
edge cases that make binning quietly wrong rather than loudly broken.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from monitoring.engine import constants as C
from monitoring.engine import profiling

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
TELCO_BASELINE = DATA / "telco_churn" / "baseline.csv"

requires_telco = pytest.mark.skipif(
    not TELCO_BASELINE.exists(),
    reason="run scripts/prepare_datasets.py first",
)


@pytest.fixture(scope="module")
def telco() -> pd.DataFrame:
    return pd.read_csv(TELCO_BASELINE)


# ──────────────────────────────────────────────────────────────────────
# classify_column
# ──────────────────────────────────────────────────────────────────────


def test_high_cardinality_numeric_is_numeric():
    series = pd.Series(np.linspace(0.0, 100.0, 500))
    assert profiling.classify_column(series) == C.NUMERIC


def test_low_cardinality_integer_is_categorical():
    """A 0/1 flag is categorical however it is stored.

    This is the SeniorCitizen case. Treating it as numeric would send it to the
    K-S test, which on two-valued data produces a statistic with no meaning.
    """
    series = pd.Series([0, 1] * 200)
    assert profiling.classify_column(series) == C.CATEGORICAL


def test_strings_are_categorical():
    assert profiling.classify_column(pd.Series(["a", "b", "c"] * 50)) == C.CATEGORICAL


def test_booleans_are_categorical():
    assert profiling.classify_column(pd.Series([True, False] * 50)) == C.CATEGORICAL


def test_cardinality_boundary():
    """At the threshold it is categorical; one above it, numeric."""
    at_limit = pd.Series(list(range(C.MAX_UNIQUE_FOR_CATEGORICAL)) * 20)
    above = pd.Series(list(range(C.MAX_UNIQUE_FOR_CATEGORICAL + 1)) * 20)
    assert profiling.classify_column(at_limit) == C.CATEGORICAL
    assert profiling.classify_column(above) == C.NUMERIC


# ──────────────────────────────────────────────────────────────────────
# suggest_exclusion
# ──────────────────────────────────────────────────────────────────────


def test_constant_column_excluded():
    reason = profiling.suggest_exclusion(pd.Series([7] * 100), "flag")
    assert reason is not None and "onstant" in reason


def test_all_unique_column_excluded():
    series = pd.Series([f"CUST-{i}" for i in range(100)])
    reason = profiling.suggest_exclusion(series, "reference")
    assert reason is not None and "identifier" in reason


def test_empty_column_excluded():
    series = pd.Series([np.nan] * 50, dtype="float64")
    assert profiling.suggest_exclusion(series, "notes") is not None


def test_id_like_name_excluded():
    series = pd.Series([1, 2, 3, 1, 2, 3] * 20)
    assert profiling.suggest_exclusion(series, "customer_id") is not None


def test_ordinary_feature_not_excluded():
    series = pd.Series(np.random.default_rng(0).normal(50, 10, 500))
    assert profiling.suggest_exclusion(series, "MonthlyCharges") is None


def test_float_column_with_unique_values_is_not_an_identifier():
    """Continuous measurements are nearly all distinct but are still features."""
    series = pd.Series(np.random.default_rng(1).normal(50, 10, 500))
    assert series.nunique() == len(series)
    assert profiling.suggest_exclusion(series, "reading") is None


# ──────────────────────────────────────────────────────────────────────
# infer_schema — against the real Telco data
# ──────────────────────────────────────────────────────────────────────


@requires_telco
def test_telco_schema_matches_acceptance_criteria(telco):
    schema = profiling.infer_schema(telco, target_column="Churn")

    # The two named in the Phase 3 acceptance criteria.
    assert schema["SeniorCitizen"]["type"] == C.CATEGORICAL
    assert schema["customerID"]["excluded"] is True
    assert schema["customerID"]["is_feature"] is False

    assert schema["MonthlyCharges"]["type"] == C.NUMERIC
    assert schema["tenure"]["type"] == C.NUMERIC
    assert schema["Contract"]["type"] == C.CATEGORICAL

    assert schema["Churn"]["is_target"] is True
    assert schema["Churn"]["is_feature"] is False


@requires_telco
def test_telco_feature_count(telco):
    """21 columns, minus the target, minus customerID, leaves 19 features."""
    schema = profiling.infer_schema(telco, target_column="Churn")
    assert len(profiling.feature_columns(schema)) == 19
    assert profiling.target_column(schema) == "Churn"


def test_missing_target_raises():
    df = pd.DataFrame({"a": [1, 2, 3]})
    with pytest.raises(ValueError, match="not present"):
        profiling.infer_schema(df, target_column="nope")


# ──────────────────────────────────────────────────────────────────────
# Binning
# ──────────────────────────────────────────────────────────────────────


def test_ten_bins_produce_eleven_edges():
    values = np.random.default_rng(0).normal(0, 1, 10_000)
    edges = profiling.build_bin_edges(values)
    assert len(edges) == C.DEFAULT_BIN_COUNT + 1
    assert edges == sorted(edges)


def test_duplicate_quantiles_are_collapsed():
    """Heavily repeated values make several quantiles identical.

    np.histogram raises on non-monotonic edges, so they must be deduplicated.
    80% zeros is not contrived — it is what a 'total_refunds' column looks like.
    """
    values = np.concatenate([np.zeros(800), np.linspace(1, 100, 200)])
    edges = profiling.build_bin_edges(values)
    assert len(edges) == len(set(edges))
    assert len(edges) >= 2
    counts = profiling.bin_counts(values, edges)
    assert sum(counts) == 1000


def test_constant_column_is_degenerate_not_an_error():
    values = np.full(100, 5.0)
    edges = profiling.build_bin_edges(values)
    assert edges == [5.0, 5.0]
    assert profiling.bin_counts(values, edges) == [100]


def test_empty_column_bins_to_nothing():
    values = np.array([np.nan] * 10)
    assert profiling.build_bin_edges(values) == []


def test_bin_counts_sum_to_non_null_count():
    values = np.concatenate([np.random.default_rng(2).normal(0, 1, 500), [np.nan] * 25])
    edges = profiling.build_bin_edges(values)
    assert sum(profiling.bin_counts(values, edges)) == 500


def test_out_of_range_values_are_counted_not_dropped():
    """The reason the outer edges are widened to +/-inf.

    A batch that has shifted beyond the baseline's range is the strongest drift
    signal there is. If those rows fell outside every bin they would be dropped,
    the proportions would stop summing to 1, and PSI would understate exactly
    the case it exists to catch.
    """
    baseline = np.linspace(0.0, 100.0, 1_000)
    edges = profiling.build_bin_edges(baseline)

    shifted = np.linspace(500.0, 600.0, 200)  # entirely outside the baseline
    counts = profiling.bin_counts(shifted, edges)

    assert sum(counts) == 200, "out-of-range values were dropped"
    assert counts[-1] == 200, "they belong in the top bin"

    below = np.linspace(-600.0, -500.0, 150)
    assert profiling.bin_counts(below, edges)[0] == 150


# ──────────────────────────────────────────────────────────────────────
# Summaries
# ──────────────────────────────────────────────────────────────────────


def test_numeric_summary_values():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    summary = profiling.summarise_numeric(series)
    assert summary["count"] == 5
    assert summary["missing"] == 0
    assert summary["mean"] == pytest.approx(3.0)
    assert summary["median"] == pytest.approx(3.0)
    assert summary["min"] == 1.0
    assert summary["max"] == 5.0


def test_numeric_summary_counts_missing():
    series = pd.Series([1.0, np.nan, 3.0, np.nan])
    summary = profiling.summarise_numeric(series)
    assert summary["count"] == 2
    assert summary["missing"] == 2
    assert summary["missing_pct"] == pytest.approx(50.0)


def test_all_null_numeric_summary_is_none_not_nan():
    """None survives JSON; NaN does not."""
    summary = profiling.summarise_numeric(pd.Series([np.nan] * 5, dtype="float64"))
    assert summary["mean"] is None
    assert summary["std"] is None
    assert summary["count"] == 0


def test_single_row_has_defined_std():
    """ddof=0, so one row gives 0.0 rather than NaN."""
    summary = profiling.summarise_numeric(pd.Series([42.0]))
    assert summary["std"] == 0.0


def test_categorical_proportions_sum_to_one():
    series = pd.Series(["a"] * 30 + ["b"] * 50 + ["c"] * 20)
    summary = profiling.summarise_categorical(series)
    assert summary["n_unique"] == 3
    assert sum(summary["proportions"].values()) == pytest.approx(1.0)
    assert summary["categories"]["b"] == 50


def test_categorical_summary_counts_missing():
    series = pd.Series(["a", None, "b", None])
    summary = profiling.summarise_categorical(series)
    assert summary["missing"] == 2
    assert summary["count"] == 2


# ──────────────────────────────────────────────────────────────────────
# build_profile
# ──────────────────────────────────────────────────────────────────────


@requires_telco
def test_profile_covers_features_only(telco):
    schema = profiling.infer_schema(telco, target_column="Churn")
    profile = profiling.build_profile(telco, schema)

    assert profile["row_count"] == len(telco)
    assert profile["feature_count"] == 19
    assert "customerID" not in profile["columns"], "excluded column was profiled"
    assert "Churn" not in profile["columns"], "target column was profiled"
    assert "MonthlyCharges" in profile["columns"]


@requires_telco
def test_profile_round_trips_through_json_losslessly(telco):
    """Acceptance criterion: JSON round-trip with no precision loss.

    NumPy scalars are the trap here — json.dumps cannot serialise np.int64, and
    the failure would only appear on a real upload.
    """
    schema = profiling.infer_schema(telco, target_column="Churn")
    profile = profiling.build_profile(telco, schema)

    restored = json.loads(json.dumps(profile))
    assert restored == profile


@requires_telco
def test_profiling_is_deterministic(telco):
    """Acceptance criterion: same input, byte-identical output."""
    schema = profiling.infer_schema(telco, target_column="Churn")
    first = json.dumps(profiling.build_profile(telco, schema), sort_keys=True)
    second = json.dumps(profiling.build_profile(telco, schema), sort_keys=True)
    assert first == second


@requires_telco
def test_numeric_bin_counts_account_for_every_row(telco):
    schema = profiling.infer_schema(telco, target_column="Churn")
    profile = profiling.build_profile(telco, schema)

    for name, entry in profile["columns"].items():
        if entry["type"] != C.NUMERIC:
            continue
        assert sum(entry["bin_counts"]) == entry["summary"]["count"], name
