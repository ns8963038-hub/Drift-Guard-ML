"""Tests for monitoring.engine.explain — PRD FR-14.

The differentiating feature of the project, so the tests check the *content* of
the sentences, not merely that a string came back.
"""

from __future__ import annotations

import pandas as pd

from monitoring.engine import constants as C
from monitoring.engine import drift, explain, profiling

TH = drift.default_thresholds()


def numeric_scores(status=C.HIGH, psi=0.34, jsd=0.23, p_value=0.0001):
    return {
        "status": status,
        "psi": psi,
        "jsd": jsd,
        "p_value": p_value,
        "test_name": C.KS,
    }


def categorical_scores(status=C.MODERATE, psi=0.18, jsd=0.14, p_value=0.0001):
    return {
        "status": status,
        "psi": psi,
        "jsd": jsd,
        "p_value": p_value,
        "test_name": C.CHI2,
    }


# ──────────────────────────────────────────────────────────────────────
# Numeric — FR-14.3
# ──────────────────────────────────────────────────────────────────────


def test_numeric_explanation_names_what_moved_and_by_how_much():
    text = explain.explain_numeric(
        "MonthlyCharges",
        {"mean": 64.80, "std": 30.09, "missing_pct": 0.0},
        {"mean": 89.32, "std": 41.57, "missing_pct": 0.0},
        numeric_scores(),
        TH,
    )

    assert "High drift" in text
    assert "MonthlyCharges" in text
    assert "64.80" in text and "89.32" in text
    assert "rose" in text
    assert "+37.8%" in text, "percentage change must be stated"
    assert "widened" in text
    assert "30.09" in text and "41.57" in text


def test_numeric_explanation_states_the_threshold_crossed():
    """FR-14.5."""
    text = explain.explain_numeric(
        "amount",
        {"mean": 10.0, "std": 2.0, "missing_pct": 0.0},
        {"mean": 30.0, "std": 3.0, "missing_pct": 0.0},
        numeric_scores(psi=0.34),
        TH,
    )
    assert "PSI is 0.340" in text
    assert "0.25" in text, "the threshold value itself must appear"
    assert "high-drift threshold" in text


def test_numeric_explanation_reports_a_confirming_test():
    text = explain.explain_numeric(
        "amount",
        {"mean": 10.0, "std": 2.0, "missing_pct": 0.0},
        {"mean": 30.0, "std": 3.0, "missing_pct": 0.0},
        numeric_scores(p_value=0.0001),
        TH,
    )
    assert "K-S test" in text
    assert "p < 0.001" in text
    assert "confirming" in text


def test_numeric_explanation_explains_a_downgrade():
    """When the shift is large but unconfirmed, say so rather than staying silent."""
    text = explain.explain_numeric(
        "amount",
        {"mean": 10.0, "std": 2.0, "missing_pct": 0.0},
        {"mean": 30.0, "std": 3.0, "missing_pct": 0.0},
        numeric_scores(status=C.MODERATE, p_value=0.42),
        TH,
    )
    assert "not statistically confirmed" in text
    assert "reduced by one level" in text


def test_numeric_explanation_handles_a_falling_mean():
    text = explain.explain_numeric(
        "tenure",
        {"mean": 40.0, "std": 5.0, "missing_pct": 0.0},
        {"mean": 20.0, "std": 3.0, "missing_pct": 0.0},
        numeric_scores(),
        TH,
    )
    assert "fell" in text
    assert "-50.0%" in text
    assert "narrowed" in text


def test_numeric_explanation_survives_a_zero_baseline_mean():
    """No division by zero — a column of zeros is a real thing."""
    text = explain.explain_numeric(
        "refunds",
        {"mean": 0.0, "std": 0.0, "missing_pct": 0.0},
        {"mean": 15.0, "std": 4.0, "missing_pct": 0.0},
        numeric_scores(),
        TH,
    )
    assert "0.00" in text and "15.00" in text
    # The percentage-change clause is omitted rather than dividing by zero.
    before_psi = text.split("PSI")[0]
    assert (
        "%)" not in before_psi
    ), "a percent change cannot be computed from a zero mean"
    assert "rose" in before_psi


def test_numeric_explanation_mentions_a_jump_in_missing_values():
    text = explain.explain_numeric(
        "TotalCharges",
        {"mean": 100.0, "std": 10.0, "missing_pct": 0.0},
        {"mean": 130.0, "std": 12.0, "missing_pct": 8.0},
        numeric_scores(),
        TH,
    )
    assert "Missing values also rose" in text
    assert "8.0%" in text


def test_clean_numeric_feature_gets_a_short_reassurance():
    text = explain.explain_numeric(
        "tenure",
        {"mean": 32.0, "std": 24.0, "missing_pct": 0.0},
        {"mean": 32.4, "std": 24.1, "missing_pct": 0.0},
        numeric_scores(status=C.NONE, psi=0.01, jsd=0.01, p_value=0.6),
        TH,
    )
    assert "No drift" in text
    assert "tenure" in text


def test_insufficient_data_says_so_explicitly():
    text = explain.explain_numeric(
        "amount",
        {"mean": 10.0, "std": 2.0, "missing_pct": 0.0},
        {"mean": 11.0, "std": 2.0, "missing_pct": 0.0, "count": 12},
        numeric_scores(status=C.INSUFFICIENT_DATA),
        TH,
    )
    assert "Not enough data" in text
    assert "30" in text, "the required minimum must be stated"


# ──────────────────────────────────────────────────────────────────────
# Categorical — FR-14.4
# ──────────────────────────────────────────────────────────────────────


def test_categorical_explanation_names_risers_and_fallers():
    text = explain.explain_categorical(
        "Contract",
        {
            "proportions": {
                "Month-to-month": 0.550,
                "One year": 0.209,
                "Two year": 0.241,
            }
        },
        {
            "proportions": {
                "Month-to-month": 0.712,
                "One year": 0.190,
                "Two year": 0.098,
            }
        },
        categorical_scores(),
        TH,
    )

    assert "Moderate drift" in text
    assert "Contract" in text
    assert "Month-to-month" in text
    assert "55.0%" in text and "71.2%" in text
    assert "+16.2 points" in text
    assert "Two year" in text
    assert "24.1%" in text and "9.8%" in text


def test_categorical_explanation_states_the_threshold():
    text = explain.explain_categorical(
        "Contract",
        {"proportions": {"a": 0.5, "b": 0.5}},
        {"proportions": {"a": 0.9, "b": 0.1}},
        categorical_scores(psi=0.18),
        TH,
    )
    assert "PSI is 0.180" in text
    assert "moderate-drift threshold of 0.10" in text


def test_categorical_explanation_reports_unseen_categories():
    text = explain.explain_categorical(
        "PaymentMethod",
        {"proportions": {"Card": 0.6, "Bank": 0.4}},
        {"proportions": {"Card": 0.3, "Bank": 0.2, "Crypto": 0.5}},
        categorical_scores(status=C.HIGH, psi=0.5),
        TH,
        unseen_categories=["Crypto"],
    )
    assert "Crypto" in text
    assert "never appeared in the baseline" in text


def test_categorical_explanation_summarises_many_unseen_categories():
    text = explain.explain_categorical(
        "code",
        {"proportions": {"A": 1.0}},
        {"proportions": {"A": 0.5, "B": 0.1, "C": 0.1, "D": 0.1, "E": 0.1, "F": 0.1}},
        categorical_scores(status=C.HIGH, psi=0.6),
        TH,
        unseen_categories=["B", "C", "D", "E", "F"],
    )
    assert "and 2 more" in text


def test_categorical_uses_chi_square_in_its_significance_clause():
    text = explain.explain_categorical(
        "Contract",
        {"proportions": {"a": 0.5, "b": 0.5}},
        {"proportions": {"a": 0.9, "b": 0.1}},
        categorical_scores(p_value=0.0001),
        TH,
    )
    assert "Chi-Square test" in text
    assert "K-S" not in text


def test_clean_categorical_feature_gets_a_short_reassurance():
    text = explain.explain_categorical(
        "gender",
        {"proportions": {"Male": 0.5, "Female": 0.5}},
        {"proportions": {"Male": 0.503, "Female": 0.497}},
        categorical_scores(status=C.NONE, psi=0.001, jsd=0.001, p_value=0.8),
        TH,
    )
    assert "No drift" in text


# ──────────────────────────────────────────────────────────────────────
# FR-14.2 — deterministic, no LLM, no network
# ──────────────────────────────────────────────────────────────────────


def test_explanations_are_deterministic():
    """The same inputs must always give byte-identical output.

    This is what allows explanations to be stored with the run and re-read
    unchanged years later (FR-14.6), and why nothing here touches a network.
    """
    args = (
        "MonthlyCharges",
        {"mean": 64.80, "std": 30.09, "missing_pct": 0.0},
        {"mean": 89.32, "std": 41.57, "missing_pct": 0.0},
        numeric_scores(),
        TH,
    )
    first = explain.explain_numeric(*args)
    for _ in range(5):
        assert explain.explain_numeric(*args) == first


def test_explain_dispatches_on_feature_type():
    numeric = {
        "feature_name": "amount",
        "feature_type": C.NUMERIC,
        "baseline_summary": {"mean": 1.0, "std": 1.0, "missing_pct": 0.0},
        "current_summary": {"mean": 5.0, "std": 2.0, "missing_pct": 0.0},
        **numeric_scores(),
    }
    categorical = {
        "feature_name": "grade",
        "feature_type": C.CATEGORICAL,
        "baseline_summary": {"proportions": {"A": 0.5, "B": 0.5}},
        "current_summary": {"proportions": {"A": 0.9, "B": 0.1}},
        "unseen_categories": [],
        **categorical_scores(),
    }

    assert "K-S test" in explain.explain(numeric, TH)
    assert "Chi-Square test" in explain.explain(categorical, TH)


def test_explain_handles_a_column_absent_from_the_batch():
    result = {
        "feature_name": "dropped",
        "feature_type": C.NUMERIC,
        "baseline_summary": {},
        "current_summary": None,
        "status": C.INSUFFICIENT_DATA,
    }
    assert "not present in this batch" in explain.explain(result, TH)


def test_explain_all_attaches_without_mutating_the_input():
    results = [
        {
            "feature_name": "amount",
            "feature_type": C.NUMERIC,
            "baseline_summary": {"mean": 1.0, "std": 1.0, "missing_pct": 0.0},
            "current_summary": {"mean": 5.0, "std": 2.0, "missing_pct": 0.0},
            **numeric_scores(),
        }
    ]
    enriched = explain.explain_all(results, TH)

    assert "explanation" in enriched[0]
    assert "explanation" not in results[0], "the input must not be mutated"


# ──────────────────────────────────────────────────────────────────────
# End to end against the real engine
# ──────────────────────────────────────────────────────────────────────


def test_real_drift_result_produces_a_usable_sentence():
    """Wire the real drift engine into the explainer and check the prose."""
    import numpy as np

    rng = np.random.default_rng(0)
    baseline_values = rng.normal(64.8, 30.1, 4000)
    edges = profiling.build_bin_edges(baseline_values)
    entry = {
        "type": C.NUMERIC,
        "bin_edges": edges,
        "bin_counts": profiling.bin_counts(baseline_values, edges),
        "summary": profiling.summarise_numeric(pd.Series(baseline_values)),
    }
    batch = pd.Series(rng.normal(89.3, 41.6, 1000))

    result = drift._analyse_numeric("MonthlyCharges", entry, baseline_values, batch, TH)
    text = explain.explain(result, TH)

    assert result["status"] == C.HIGH
    assert text.startswith("High drift detected in `MonthlyCharges`.")
    assert "rose" in text and "widened" in text
    assert "PSI is" in text
    assert "p < 0.001" in text
    assert len(text) > 150, "an explanation this thin would not be useful"
