"""End-to-end tests for monitoring.engine.pipeline.

Runs the complete cycle — quality, drift, performance, health, explain — against
real Telco data and a real trained artifact. If these pass, the engine works;
everything remaining is Django plumbing around it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from monitoring.engine import constants as C
from monitoring.engine import drift, pipeline, profiling

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed" / "telco_churn"
MANIFEST = ROOT / "artifacts" / "manifest.json"

requires_artifacts = pytest.mark.skipif(
    not MANIFEST.exists() or not (DATA / "baseline.csv").exists(),
    reason="run scripts/prepare_datasets.py then scripts/train_demo_models.py",
)


@pytest.fixture(scope="module")
def setup():
    """Everything a monitoring run needs, exactly as the Django layer will supply it."""
    import joblib

    baseline = pd.read_csv(DATA / "baseline.csv")
    schema = profiling.infer_schema(baseline, "Churn")
    profile = profiling.build_profile(baseline, schema)

    manifest = json.loads(MANIFEST.read_text())
    entry = next(
        m for m in manifest if m["dataset"] == "telco_churn" and m["version"] == "V2"
    )
    model = joblib.load(ROOT / entry["artifact"])

    features = profiling.feature_columns(schema)
    baseline_predictions = model.predict(baseline[features])
    baseline_distribution = (
        pd.Series(baseline_predictions).value_counts(normalize=True).to_dict()
    )

    return {
        "baseline": baseline,
        "schema": schema,
        "profile": profile,
        "model": model,
        "entry": entry,
        "baseline_distribution": baseline_distribution,
    }


def run(setup, batch, **overrides):
    kwargs = dict(
        thresholds=drift.default_thresholds(),
        baseline_prediction_distribution=setup["baseline_distribution"],
        reference_accuracy=setup["entry"]["training_accuracy"],
        target_column="Churn",
        class_labels=setup["entry"]["classes"],
        positive_class=setup["entry"]["positive_class"],
    )
    kwargs.update(overrides)
    return pipeline.run_monitoring(
        batch,
        setup["profile"],
        setup["baseline"],
        setup["schema"],
        setup["model"],
        **kwargs,
    )


# ──────────────────────────────────────────────────────────────────────
# Shape of the result
# ──────────────────────────────────────────────────────────────────────


@requires_artifacts
def test_result_has_every_section(setup):
    result = run(setup, pd.read_csv(DATA / "holdout.csv"))

    assert set(result) == {"quality", "drift", "performance", "health", "meta"}
    assert set(result["drift"]) == {"features", "overall_status", "counts"}
    assert result["meta"]["row_count"] == 1409
    assert result["meta"]["features_monitored"] == 19
    assert result["meta"]["duration_ms"] >= 0
    assert result["meta"]["thresholds"]["psi_high"] == 0.25


@requires_artifacts
def test_every_feature_gets_an_explanation(setup):
    """FR-14.1 — explanations are attached by the pipeline, not on read."""
    result = run(setup, pd.read_csv(DATA / "holdout.csv"))

    for feature in result["drift"]["features"]:
        assert feature["explanation"], f"{feature['feature_name']} has no explanation"
        assert feature["feature_name"] in feature["explanation"]


@requires_artifacts
def test_counts_match_the_feature_list(setup):
    result = run(setup, pd.read_csv(DATA / "holdout.csv"))
    counts = result["drift"]["counts"]

    assert counts["total"] == len(result["drift"]["features"])
    assert (
        counts["high"] + counts["moderate"] + counts["none"] + counts["insufficient"]
        == counts["total"]
    )


# ──────────────────────────────────────────────────────────────────────
# A clean batch
# ──────────────────────────────────────────────────────────────────────


@requires_artifacts
def test_clean_holdout_is_healthy(setup):
    """The whole engine's sanity check: same population in, nothing wrong out."""
    result = run(setup, pd.read_csv(DATA / "holdout.csv"))

    assert result["drift"]["overall_status"] == C.NONE
    assert result["drift"]["counts"]["high"] == 0
    assert result["drift"]["counts"]["moderate"] == 0
    assert result["quality"]["quality_score"] >= 90
    assert result["performance"]["labels_available"] is True
    assert result["health"]["band"] == "HEALTHY"
    assert result["health"]["score"] >= 80


# ──────────────────────────────────────────────────────────────────────
# A drifted batch
# ──────────────────────────────────────────────────────────────────────


@requires_artifacts
def test_drifted_batch_degrades_every_signal(setup):
    """The demo scenario end to end.

    Shift MonthlyCharges, flip the Contract mix, inject nulls, duplicates and an
    unseen category — then assert the platform notices all of it.
    """
    baseline = setup["baseline"]
    batch = pd.read_csv(DATA / "holdout.csv").copy()
    rng = np.random.default_rng(5)

    batch["MonthlyCharges"] = (
        batch["MonthlyCharges"] + 2.5 * baseline["MonthlyCharges"].std()
    )
    batch["Contract"] = rng.choice(
        ["Month-to-month", "One year", "Two year"], len(batch), p=[0.92, 0.05, 0.03]
    )
    batch.loc[batch.index[:120], "TotalCharges"] = np.nan
    batch["PaymentMethod"] = np.where(
        rng.random(len(batch)) < 0.30, "Crypto Wallet", batch["PaymentMethod"]
    )
    batch = pd.concat([batch, batch.head(90)], ignore_index=True)

    result = run(setup, batch)

    # drift
    assert result["drift"]["overall_status"] == C.HIGH
    assert result["drift"]["counts"]["high"] >= 2
    by_name = {f["feature_name"]: f for f in result["drift"]["features"]}
    assert by_name["MonthlyCharges"]["status"] == C.HIGH
    assert by_name["Contract"]["status"] == C.HIGH

    # quality
    assert result["quality"]["duplicate_rows"] == 90
    # 120 injected nulls, plus 90 more carried in by duplicating the first 90
    # rows — which all fell inside the injected range. The faults compound,
    # exactly as they would in a real broken feed.
    assert result["quality"]["missing_total"] == 210
    assert "PaymentMethod" in result["quality"]["unseen_category_columns"]
    assert result["quality"]["quality_score"] < 90

    # health
    assert result["health"]["band"] in ("WARNING", "CRITICAL")
    assert (
        result["health"]["capped"] is True
    ), "PRD 8.4a: HIGH drift cannot read HEALTHY"
    assert result["health"]["components"]["drift"] < 80

    # explanation quality
    explanation = by_name["MonthlyCharges"]["explanation"]
    assert "High drift" in explanation
    assert "rose" in explanation and "PSI is" in explanation


@requires_artifacts
def test_worst_features_come_first(setup):
    """FR-08.2 — the run detail table defaults to worst-drift-first."""
    baseline = setup["baseline"]
    batch = pd.read_csv(DATA / "holdout.csv").copy()
    batch["MonthlyCharges"] += 3 * baseline["MonthlyCharges"].std()

    result = run(setup, batch)
    statuses = [f["status"] for f in result["drift"]["features"]]
    order = {C.HIGH: 0, C.MODERATE: 1, C.NONE: 2, C.INSUFFICIENT_DATA: 3}
    assert statuses == sorted(statuses, key=lambda s: order[s])


# ──────────────────────────────────────────────────────────────────────
# The unlabelled path
# ──────────────────────────────────────────────────────────────────────


@requires_artifacts
def test_unlabelled_batch_still_produces_a_full_run(setup):
    """The realistic production case, and the one most likely to be broken.

    No ground truth: drift, quality and prediction distribution must all still
    work, performance metrics must be None rather than zero, and health must
    switch to the redistributed weighting instead of scoring the model down.
    """
    batch = pd.read_csv(DATA / "holdout.csv").drop(columns=["Churn"])
    result = run(setup, batch)

    assert result["performance"]["labels_available"] is False
    assert result["performance"]["accuracy"] is None
    assert result["performance"]["prediction_distribution"]["total"] == len(batch)

    assert result["drift"]["counts"]["total"] == 19
    assert result["quality"]["quality_score"] >= 90

    assert result["health"]["weighting"] == "without_labels"
    assert result["health"]["components"]["performance"] is None
    assert (
        result["health"]["band"] == "HEALTHY"
    ), "an unlabelled batch is not a sick model"


# ──────────────────────────────────────────────────────────────────────
# Contracts the Django layer relies on
# ──────────────────────────────────────────────────────────────────────


@requires_artifacts
def test_result_is_json_serialisable(setup):
    """Everything here is persisted as JSON fields, so it must survive the trip."""
    result = run(setup, pd.read_csv(DATA / "holdout.csv"))
    assert json.loads(json.dumps(result)) == result


@requires_artifacts
def test_pipeline_is_reproducible(setup):
    """PRD NFR-14 — the same batch scored twice gives identical numbers."""
    batch = pd.read_csv(DATA / "holdout.csv")
    first, second = run(setup, batch), run(setup, batch)

    for key in ("quality", "drift", "performance", "health"):
        assert json.dumps(first[key], sort_keys=True) == json.dumps(
            second[key], sort_keys=True
        ), key


@requires_artifacts
def test_scoring_failure_propagates_for_the_caller_to_handle(setup):
    """BACKEND_FLOW §4.3 — a model that cannot predict fails the run loudly."""
    from monitoring.engine import performance

    class Broken:
        def predict(self, X):
            raise RuntimeError("feature names mismatch")

    with pytest.raises(performance.ScoringError):
        pipeline.run_monitoring(
            pd.read_csv(DATA / "holdout.csv"),
            setup["profile"],
            setup["baseline"],
            setup["schema"],
            Broken(),
            target_column="Churn",
        )


@requires_artifacts
def test_tiny_batch_completes_without_pretending_to_know_things(setup):
    result = run(setup, pd.read_csv(DATA / "holdout.csv").head(8))

    assert result["drift"]["counts"]["insufficient"] == 19
    assert result["drift"]["overall_status"] == C.NONE
    assert result["meta"]["row_count"] == 8
