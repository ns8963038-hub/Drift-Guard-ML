"""Tests for simulator.transforms — PRD FR-05.7.

The simulator is what makes the demo work unattended, so the tests check that
each transformation produces drift the *detector* actually catches, not merely
that the numbers moved.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from monitoring.engine import constants as C
from monitoring.engine import drift, profiling
from simulator import transforms

DATA = Path(__file__).resolve().parent.parent / "data" / "processed" / "telco_churn"

requires_telco = pytest.mark.skipif(
    not (DATA / "baseline.csv").exists(), reason="run scripts/prepare_datasets.py first"
)


@pytest.fixture(scope="module")
def telco():
    baseline = pd.read_csv(DATA / "baseline.csv")
    holdout = pd.read_csv(DATA / "holdout.csv")
    schema = profiling.infer_schema(baseline, "Churn")
    profile = profiling.build_profile(baseline, schema)
    return baseline, holdout, schema, profile


def rng(seed: int = 0) -> np.random.Generator:
    return np.random.default_rng(seed)


def simple():
    """A small baseline with one numeric and one categorical column."""
    generator = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "amount": generator.normal(100.0, 20.0, 2000),
            "grade": generator.choice(["A", "B", "C"], 2000, p=[0.6, 0.3, 0.1]),
            "target": generator.choice(["yes", "no"], 2000),
        }
    )
    schema = profiling.infer_schema(frame, "target")
    return frame, schema, profiling.build_profile(frame, schema)


# ──────────────────────────────────────────────────────────────────────
# numeric_shift
# ──────────────────────────────────────────────────────────────────────


def test_numeric_shift_moves_the_mean_by_the_stated_sigma():
    frame, _, profile = simple()
    std = profile["columns"]["amount"]["summary"]["std"]

    shifted = transforms.numeric_shift(frame, "amount", 2.0, profile, rng())

    assert shifted["amount"].mean() == pytest.approx(frame["amount"].mean() + 2 * std)
    assert shifted["amount"].std() == pytest.approx(frame["amount"].std())


def test_numeric_shift_accepts_a_negative_sigma():
    frame, _, profile = simple()
    shifted = transforms.numeric_shift(frame, "amount", -1.5, profile, rng())
    assert shifted["amount"].mean() < frame["amount"].mean()


def test_numeric_shift_on_a_constant_column_is_a_no_op():
    """No standard deviation to scale by, so nothing pretends to have happened."""
    frame = pd.DataFrame({"flat": [5.0] * 100, "target": ["a"] * 100})
    profile = {"columns": {"flat": {"summary": {"std": 0.0}}}}

    result = transforms.numeric_shift(frame, "flat", 3.0, profile, rng())
    assert result["flat"].tolist() == frame["flat"].tolist()


def test_numeric_shift_leaves_other_columns_alone():
    frame, _, profile = simple()
    shifted = transforms.numeric_shift(frame, "amount", 2.0, profile, rng())
    assert shifted["grade"].tolist() == frame["grade"].tolist()


# ──────────────────────────────────────────────────────────────────────
# numeric_scale
# ──────────────────────────────────────────────────────────────────────


def test_numeric_scale_widens_spread_without_moving_the_centre():
    frame, _, profile = simple()
    scaled = transforms.numeric_scale(frame, "amount", 2.0, profile, rng())

    assert scaled["amount"].mean() == pytest.approx(frame["amount"].mean())
    assert scaled["amount"].std() == pytest.approx(frame["amount"].std() * 2.0)


def test_numeric_scale_can_narrow():
    frame, _, profile = simple()
    scaled = transforms.numeric_scale(frame, "amount", 0.5, profile, rng())
    assert scaled["amount"].std() < frame["amount"].std()


def test_shift_then_scale_compose():
    """Scaling around the current mean keeps a prior shift intact."""
    frame, _, profile = simple()
    std = profile["columns"]["amount"]["summary"]["std"]

    result = transforms.numeric_shift(frame, "amount", 2.0, profile, rng())
    result = transforms.numeric_scale(result, "amount", 1.5, profile, rng())

    assert result["amount"].mean() == pytest.approx(frame["amount"].mean() + 2 * std)
    assert result["amount"].std() == pytest.approx(frame["amount"].std() * 1.5)


# ──────────────────────────────────────────────────────────────────────
# category_shift
# ──────────────────────────────────────────────────────────────────────


def test_category_shift_hits_the_target_proportions():
    frame, _, _ = simple()
    result = transforms.category_shift(
        frame, "grade", {"A": 0.1, "B": 0.2, "C": 0.7}, rng()
    )

    proportions = result["grade"].value_counts(normalize=True)
    assert proportions["C"] == pytest.approx(0.7, abs=0.02)
    assert proportions["A"] == pytest.approx(0.1, abs=0.02)


def test_category_shift_preserves_row_count():
    frame, _, _ = simple()
    result = transforms.category_shift(frame, "grade", {"A": 0.5, "C": 0.5}, rng())
    assert len(result) == len(frame)


def test_category_shift_resamples_whole_rows():
    """Correlations survive, because rows are resampled rather than overwritten.

    If the column were overwritten in place, every row would keep the other
    values of whatever category it used to be — producing batches that are
    internally incoherent in a way real drift never is.
    """
    generator = np.random.default_rng(1)
    frame = pd.DataFrame(
        {
            # amount is entirely determined by grade
            "grade": ["A"] * 500 + ["B"] * 500,
            "amount": [10.0] * 500 + [100.0] * 500,
            "target": generator.choice(["yes", "no"], 1000),
        }
    )
    result = transforms.category_shift(frame, "grade", {"A": 0.1, "B": 0.9}, rng())

    # The relationship must still hold row by row.
    assert (result.loc[result["grade"] == "A", "amount"] == 10.0).all()
    assert (result.loc[result["grade"] == "B", "amount"] == 100.0).all()
    # And the co-drift is real: shifting grade dragged amount with it.
    assert result["amount"].mean() > frame["amount"].mean()


def test_category_shift_redistributes_absent_categories():
    """A plan may name a category the source rows do not contain."""
    frame, _, _ = simple()
    result = transforms.category_shift(
        frame, "grade", {"A": 0.5, "NEVER_SEEN": 0.5}, rng()
    )
    assert set(result["grade"]) == {"A"}
    assert len(result) == len(frame)


def test_category_shift_with_no_usable_targets_is_a_no_op():
    frame, _, _ = simple()
    result = transforms.category_shift(frame, "grade", {"NOPE": 1.0}, rng())
    assert len(result) == len(frame)


# ──────────────────────────────────────────────────────────────────────
# missing / duplicate / outlier injection
# ──────────────────────────────────────────────────────────────────────


def test_missing_injection_blanks_the_requested_fraction():
    frame, _, _ = simple()
    result = transforms.missing_injection(frame, "amount", 0.10, rng())

    assert result["amount"].isna().sum() == 200
    assert result["grade"].isna().sum() == 0


def test_missing_injection_of_zero_changes_nothing():
    frame, _, _ = simple()
    assert (
        transforms.missing_injection(frame, "amount", 0.0, rng())["amount"].isna().sum()
        == 0
    )


def test_duplicate_injection_grows_the_batch():
    """A double-delivering feed produces more rows, not the same rows re-flagged."""
    frame, _, _ = simple()
    result = transforms.duplicate_injection(frame, 0.10, rng())

    assert len(result) == 2200
    assert result.duplicated().sum() >= 200


def test_outlier_injection_lands_outside_tukeys_fence():
    frame, _, profile = simple()
    summary = profile["columns"]["amount"]["summary"]
    upper_fence = summary["q3"] + 1.5 * (summary["q3"] - summary["q1"])

    result = transforms.outlier_injection(frame, "amount", 0.05, profile, rng())

    beyond = (result["amount"] > upper_fence).sum()
    assert beyond >= 100, "injected values must clear the fence the detector uses"


def test_outlier_injection_falls_back_when_the_baseline_has_no_iqr():
    frame = pd.DataFrame({"flat": [5.0] * 100, "target": ["a"] * 100})
    profile = {
        "columns": {"flat": {"summary": {"q1": 5.0, "q3": 5.0, "std": 0.0, "max": 5.0}}}
    }
    result = transforms.outlier_injection(frame, "flat", 0.1, profile, rng())
    assert result["flat"].tolist() == frame["flat"].tolist()


# ──────────────────────────────────────────────────────────────────────
# Drift plans
# ──────────────────────────────────────────────────────────────────────


def test_phases_are_cumulative_not_intervals():
    """Batch 30 uses the batch-25 phase, not 'nothing'."""
    plan = {
        "phases": [
            {"from_batch": 0, "transformations": []},
            {"from_batch": 10, "transformations": [{"type": "a"}]},
            {"from_batch": 25, "transformations": [{"type": "b"}]},
        ]
    }
    assert transforms.resolve_phase(plan, 0)["from_batch"] == 0
    assert transforms.resolve_phase(plan, 9)["from_batch"] == 0
    assert transforms.resolve_phase(plan, 10)["from_batch"] == 10
    assert transforms.resolve_phase(plan, 24)["from_batch"] == 10
    assert transforms.resolve_phase(plan, 25)["from_batch"] == 25
    assert transforms.resolve_phase(plan, 999)["from_batch"] == 25


def test_phases_out_of_order_still_resolve():
    plan = {
        "phases": [
            {"from_batch": 20, "transformations": [{"type": "late"}]},
            {"from_batch": 0, "transformations": []},
        ]
    }
    assert transforms.resolve_phase(plan, 5)["from_batch"] == 0
    assert transforms.resolve_phase(plan, 25)["from_batch"] == 20


def test_empty_plan_resolves_to_no_drift():
    assert transforms.resolve_phase({}, 5)["transformations"] == []


@requires_telco
def test_validate_accepts_a_real_plan(telco):
    _, _, schema, _ = telco
    plan = transforms.default_scenario("MonthlyCharges", "Contract")
    transforms.validate_drift_plan(plan, schema)  # must not raise


@requires_telco
def test_validate_rejects_an_unknown_column(telco):
    _, _, schema, _ = telco
    plan = {
        "phases": [
            {
                "from_batch": 0,
                "transformations": [
                    {
                        "type": "numeric_shift",
                        "column": "NoSuchColumn",
                        "mean_delta_sigma": 1,
                    }
                ],
            }
        ]
    }
    with pytest.raises(transforms.DriftPlanError, match="not in the schema"):
        transforms.validate_drift_plan(plan, schema)


@requires_telco
def test_validate_rejects_an_excluded_column(telco):
    """Drifting customerID would be invisible — the detector never looks at it."""
    _, _, schema, _ = telco
    plan = {
        "phases": [
            {
                "from_batch": 0,
                "transformations": [
                    {"type": "missing_injection", "column": "customerID", "rate": 0.1}
                ],
            }
        ]
    }
    with pytest.raises(transforms.DriftPlanError, match="excluded from monitoring"):
        transforms.validate_drift_plan(plan, schema)


def test_validate_rejects_unknown_transformation_types():
    schema = {"a": {"is_feature": True}}
    plan = {
        "phases": [
            {"from_batch": 0, "transformations": [{"type": "teleport", "column": "a"}]}
        ]
    }
    with pytest.raises(transforms.DriftPlanError, match="Unknown transformation"):
        transforms.validate_drift_plan(plan, schema)


def test_validate_rejects_duplicate_phase_indices():
    schema = {"a": {"is_feature": True}}
    plan = {
        "phases": [
            {"from_batch": 5, "transformations": []},
            {"from_batch": 5, "transformations": []},
        ]
    }
    with pytest.raises(transforms.DriftPlanError, match="both start at batch 5"):
        transforms.validate_drift_plan(plan, schema)


def test_validate_rejects_an_empty_plan():
    with pytest.raises(transforms.DriftPlanError, match="non-empty"):
        transforms.validate_drift_plan({"phases": []}, {})


def test_duplicate_injection_needs_no_column():
    schema = {"a": {"is_feature": True}}
    plan = {
        "phases": [
            {
                "from_batch": 0,
                "transformations": [{"type": "duplicate_injection", "rate": 0.1}],
            }
        ]
    }
    transforms.validate_drift_plan(plan, schema)  # must not raise


# ──────────────────────────────────────────────────────────────────────
# build_batch
# ──────────────────────────────────────────────────────────────────────


@requires_telco
def test_build_batch_returns_the_requested_size(telco):
    _, holdout, _, profile = telco
    batch = transforms.build_batch(holdout, profile, {"phases": []}, 0, 500)
    assert len(batch) == 500


@requires_telco
def test_build_batch_is_reproducible(telco):
    """PRD NFR-14 — a rehearsed demo replays identically."""
    _, holdout, _, profile = telco
    plan = transforms.default_scenario("MonthlyCharges", "Contract")

    first = transforms.build_batch(holdout, profile, plan, 30, 300)
    second = transforms.build_batch(holdout, profile, plan, 30, 300)
    pd.testing.assert_frame_equal(first, second)


@requires_telco
def test_consecutive_batches_differ(telco):
    _, holdout, _, profile = telco
    first = transforms.build_batch(holdout, profile, {"phases": []}, 0, 300)
    second = transforms.build_batch(holdout, profile, {"phases": []}, 1, 300)
    assert not first.equals(second)


@requires_telco
def test_build_batch_can_withhold_labels(telco):
    _, holdout, _, profile = telco
    batch = transforms.build_batch(
        holdout,
        profile,
        {"phases": []},
        0,
        200,
        include_labels=False,
        target_column="Churn",
    )
    assert "Churn" not in batch.columns
    assert len(batch) == 200


@requires_telco
def test_build_batch_keeps_labels_by_default(telco):
    _, holdout, _, profile = telco
    batch = transforms.build_batch(holdout, profile, {"phases": []}, 0, 200)
    assert "Churn" in batch.columns


def test_build_batch_rejects_an_empty_holdout():
    with pytest.raises(transforms.DriftPlanError, match="holdout pool is empty"):
        transforms.build_batch(pd.DataFrame(), {}, {"phases": []}, 0, 100)


# ──────────────────────────────────────────────────────────────────────
# The whole point: does the detector actually catch it?
# ──────────────────────────────────────────────────────────────────────


@requires_telco
def test_the_demo_scenario_progresses_none_to_moderate_to_high(telco):
    """FR-05 acceptance criterion, verified against the real detector.

    Feeding the default scenario through the drift engine must produce a clean
    stretch, then moderate drift, then high drift — with no human involved. If
    this passes, the centrepiece of the demo works.
    """
    baseline, holdout, schema, profile = telco

    plan = transforms.default_scenario("MonthlyCharges", "Contract")
    plan["phases"][2]["transformations"][2]["target_proportions"] = {
        "Month-to-month": 0.90,
        "One year": 0.07,
        "Two year": 0.03,
    }
    transforms.validate_drift_plan(plan, schema)

    def status_at(batch_index: int) -> str:
        batch = transforms.build_batch(holdout, profile, plan, batch_index, 600)
        results = drift.analyse_features(profile, baseline, batch, schema)
        return drift.rollup(results)

    assert status_at(3) == C.NONE, "the clean phase must look clean"
    assert status_at(15) == C.MODERATE, "phase 2 must be amber, not straight to red"
    assert status_at(30) == C.HIGH, "phase 3 must be unambiguous"


@requires_telco
def test_injected_faults_are_caught_by_the_quality_module(telco):
    """The simulator and the quality checks must agree about what was injected."""
    from monitoring.engine import quality

    baseline, holdout, schema, profile = telco
    plan = {
        "phases": [
            {
                "from_batch": 0,
                "transformations": [
                    {
                        "type": "missing_injection",
                        "column": "TotalCharges",
                        "rate": 0.08,
                    },
                    {"type": "outlier_injection", "column": "tenure", "rate": 0.05},
                    {"type": "duplicate_injection", "rate": 0.10},
                ],
            }
        ]
    }
    transforms.validate_drift_plan(plan, schema)

    batch = transforms.build_batch(holdout, profile, plan, 0, 500)
    report = quality.assess(batch, profile, schema)

    assert report["missing_total"] > 0
    assert report["duplicate_rows"] > 0
    assert "tenure" in report["outlier_counts"]
    assert report["quality_score"] < 95


@requires_telco
def test_describe_phase_reads_as_english(telco):
    plan = transforms.default_scenario("MonthlyCharges", "Contract")

    assert "No drift" in transforms.describe_phase(plan["phases"][0])
    described = transforms.describe_phase(plan["phases"][2])
    assert "MonthlyCharges shifted +2.2σ" in described
    assert "duplicate rows" in described


def test_copy_plan_does_not_share_state():
    plan = transforms.default_scenario("a", "b")
    duplicate = transforms.copy_plan(plan)
    duplicate["phases"][1]["transformations"][0]["mean_delta_sigma"] = 99

    assert plan["phases"][1]["transformations"][0]["mean_delta_sigma"] == 2.0


def test_default_scenario_starts_clean():
    """A demo that begins already broken shows nothing."""
    plan = transforms.default_scenario("x", "y")
    assert plan["phases"][0]["from_batch"] == 0
    assert plan["phases"][0]["transformations"] == []
    assert json.dumps(plan)  # must be storable as JSON
