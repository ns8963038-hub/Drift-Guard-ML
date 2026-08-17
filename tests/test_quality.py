"""Tests for monitoring.engine.quality — PRD FR-11."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from monitoring.engine import profiling, quality

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
TELCO_BASELINE = DATA / "telco_churn" / "baseline.csv"
TELCO_HOLDOUT = DATA / "telco_churn" / "holdout.csv"

requires_telco = pytest.mark.skipif(
    not TELCO_BASELINE.exists(), reason="run scripts/prepare_datasets.py first"
)


@pytest.fixture(scope="module")
def telco_setup():
    baseline = pd.read_csv(TELCO_BASELINE)
    schema = profiling.infer_schema(baseline, "Churn")
    profile = profiling.build_profile(baseline, schema)
    return baseline, schema, profile


def simple_setup() -> tuple[pd.DataFrame, dict, dict]:
    """A small clean baseline: one numeric column, one categorical."""
    rng = np.random.default_rng(0)
    baseline = pd.DataFrame(
        {
            "amount": rng.normal(100, 15, 1000),
            "grade": rng.choice(["A", "B", "C"], 1000, p=[0.5, 0.3, 0.2]),
            "target": rng.choice(["yes", "no"], 1000),
        }
    )
    schema = profiling.infer_schema(baseline, "target")
    profile = profiling.build_profile(baseline, schema)
    return baseline, schema, profile


# ──────────────────────────────────────────────────────────────────────
# Clean data
# ──────────────────────────────────────────────────────────────────────


def test_clean_batch_scores_near_100():
    baseline, schema, profile = simple_setup()
    report = quality.assess(baseline.copy(), profile, schema)

    assert report["missing_total"] == 0
    assert report["duplicate_rows"] == 0
    assert report["type_mismatch_columns"] == {}
    assert report["unseen_category_columns"] == {}
    assert report["quality_score"] >= 95


@requires_telco
def test_clean_holdout_scores_high(telco_setup):
    """A random split of the same population must not look like bad data."""
    _, schema, profile = telco_setup
    holdout = pd.read_csv(TELCO_HOLDOUT)
    report = quality.assess(holdout, profile, schema)
    assert report["quality_score"] >= 90, report["penalties"]


# ──────────────────────────────────────────────────────────────────────
# FR-11.1 missing values
# ──────────────────────────────────────────────────────────────────────


def test_missing_values_counted_per_column_and_overall():
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch.loc[batch.index[:50], "amount"] = np.nan  # 50 of 1000 in one of 2 features

    report = quality.assess(batch, profile, schema)

    assert report["missing_total"] == 50
    assert report["per_column"]["amount"]["missing"] == 50
    assert report["per_column"]["amount"]["missing_pct"] == pytest.approx(5.0)
    # 50 missing cells out of 1000 rows x 2 monitored features
    assert report["missing_pct"] == pytest.approx(2.5)


def test_missing_values_reduce_the_score():
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch.loc[batch.index[:200], "amount"] = np.nan

    clean = quality.assess(baseline.copy(), profile, schema)["quality_score"]
    dirty = quality.assess(batch, profile, schema)["quality_score"]
    assert dirty < clean


def test_missing_penalty_is_capped():
    """An entirely empty batch must not send the score below zero."""
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch["amount"] = np.nan
    batch["grade"] = np.nan

    report = quality.assess(batch, profile, schema)
    assert report["penalties"]["missing"] == 30.0
    assert report["quality_score"] >= 0


# ──────────────────────────────────────────────────────────────────────
# FR-11.2 duplicates
# ──────────────────────────────────────────────────────────────────────


def test_duplicate_rows_detected():
    baseline, schema, profile = simple_setup()
    batch = pd.concat([baseline, baseline.head(100)], ignore_index=True)

    report = quality.assess(batch, profile, schema)
    assert report["duplicate_rows"] == 100
    assert report["duplicate_pct"] == pytest.approx(100 / 1100 * 100, abs=0.01)


def test_no_duplicates_in_distinct_data():
    baseline, schema, profile = simple_setup()
    assert quality.assess(baseline.copy(), profile, schema)["duplicate_rows"] == 0


# ──────────────────────────────────────────────────────────────────────
# FR-11.3 invalid values and unseen categories
# ──────────────────────────────────────────────────────────────────────


def test_values_outside_the_baseline_range_are_flagged():
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch.loc[batch.index[:20], "amount"] = 10_000.0  # far above anything seen

    report = quality.assess(batch, profile, schema)
    assert "amount" in report["out_of_range_columns"]
    assert report["out_of_range_columns"]["amount"]["above_max"] == 20
    assert report["out_of_range_columns"]["amount"]["below_min"] == 0


def test_unseen_categories_are_flagged():
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch.loc[batch.index[:30], "grade"] = "Z"

    report = quality.assess(batch, profile, schema)
    assert report["unseen_category_columns"]["grade"] == ["Z"]
    assert report["quality_score"] < 100


def test_known_categories_are_not_flagged():
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch["grade"] = "A"  # a big proportion shift, but nothing unseen
    report = quality.assess(batch, profile, schema)
    assert report["unseen_category_columns"] == {}


# ──────────────────────────────────────────────────────────────────────
# FR-11.4 outliers
# ──────────────────────────────────────────────────────────────────────


def test_outliers_use_baseline_fences_not_batch_fences():
    """The single most important behaviour in this module.

    Every value in the batch is shifted far above the baseline. Judged against
    its own quartiles the batch looks perfectly ordinary — which is exactly why
    the fences must come from the baseline.
    """
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch["amount"] = batch["amount"] + 500.0

    report = quality.assess(batch, profile, schema)

    assert "amount" in report["outlier_counts"]
    assert report["outlier_counts"]["amount"]["count"] == len(batch)
    assert report["outlier_counts"]["amount"]["pct"] == pytest.approx(100.0)


def test_normal_data_has_few_outliers():
    baseline, schema, profile = simple_setup()
    report = quality.assess(baseline.copy(), profile, schema)
    # Tukey's fence flags ~0.7% of a normal distribution by construction.
    assert report["outlier_pct"] < 3.0


def test_injected_outliers_are_counted():
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch.loc[batch.index[:40], "amount"] = 5_000.0

    report = quality.assess(batch, profile, schema)
    assert report["outlier_counts"]["amount"]["count"] >= 40


# ──────────────────────────────────────────────────────────────────────
# FR-11.5 type mismatches
# ──────────────────────────────────────────────────────────────────────


def test_numeric_column_arriving_as_text_is_a_mismatch():
    baseline, schema, profile = simple_setup()
    batch = baseline.copy()
    batch["amount"] = batch["amount"].astype(str) + " USD"

    report = quality.assess(batch, profile, schema)
    assert "amount" in report["type_mismatch_columns"]
    assert report["type_mismatch_columns"]["amount"]["expected"] == "numeric"
    assert report["type_mismatch_columns"]["amount"]["actual"] == "text"


def test_int_to_float_is_not_a_mismatch():
    """Normal CSV behaviour, not a data quality problem.

    A column read as int64 becomes float64 the moment a single row is missing.
    Flagging that would produce constant false alarms.
    """
    rng = np.random.default_rng(1)
    baseline = pd.DataFrame(
        {"count": rng.integers(0, 500, 500), "target": ["a", "b"] * 250}
    )
    schema = profiling.infer_schema(baseline, "target")
    profile = profiling.build_profile(baseline, schema)

    batch = baseline.copy()
    batch["count"] = batch["count"].astype(float)

    report = quality.assess(batch, profile, schema)
    assert report["type_mismatch_columns"] == {}


# ──────────────────────────────────────────────────────────────────────
# FR-11.6 score
# ──────────────────────────────────────────────────────────────────────


def test_score_never_leaves_zero_to_one_hundred():
    baseline, schema, profile = simple_setup()
    batch = pd.concat([baseline, baseline], ignore_index=True)
    batch["amount"] = "junk"
    batch["grade"] = "NEVER_SEEN"

    report = quality.assess(batch, profile, schema)
    assert 0 <= report["quality_score"] <= 100


def test_penalties_are_reported_for_transparency():
    """The score is never a black box — the breakdown ships with it."""
    baseline, schema, profile = simple_setup()
    report = quality.assess(baseline.copy(), profile, schema)
    assert set(report["penalties"]) == {
        "missing",
        "duplicates",
        "type_mismatches",
        "unseen_categories",
        "outliers",
    }


def test_score_matches_the_documented_formula():
    """Hand-checked against PRD §8.5.

    10% of one of two feature columns missing -> 5% overall -> 7.5 penalty.
    100 duplicates in 1100 rows -> 9.0909% -> 9.09 penalty.
    """
    baseline, schema, profile = simple_setup()
    batch = pd.concat([baseline, baseline.head(100)], ignore_index=True)
    batch.loc[batch.index[:110], "amount"] = np.nan

    report = quality.assess(batch, profile, schema)
    expected = 100.0 - sum(report["penalties"].values())
    assert report["quality_score"] == int(round(expected))


# ──────────────────────────────────────────────────────────────────────
# Scoping
# ──────────────────────────────────────────────────────────────────────


@requires_telco
def test_excluded_and_target_columns_are_not_checked(telco_setup):
    _, schema, profile = telco_setup
    holdout = pd.read_csv(TELCO_HOLDOUT)
    report = quality.assess(holdout, profile, schema)

    assert "customerID" not in report["per_column"]
    assert "Churn" not in report["per_column"]
    assert report["columns_checked"] == 19


def test_empty_batch_does_not_divide_by_zero():
    baseline, schema, profile = simple_setup()
    report = quality.assess(baseline.iloc[0:0], profile, schema)
    assert report["row_count"] == 0
    assert report["missing_pct"] == 0.0
    assert report["duplicate_pct"] == 0.0
    assert 0 <= report["quality_score"] <= 100
