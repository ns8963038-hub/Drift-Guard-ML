"""Tests for monitoring.engine.performance — PRD FR-04.

The contract these exist to protect is FR-04.5: an unlabelled batch produces
``None`` metrics, never ``0``. Every other property here is ordinary; that one
is the difference between a working performance chart and one that reads as a
cliff every time production data arrives without ground truth.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from monitoring.engine import performance, profiling

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
TELCO_BASELINE = DATA / "telco_churn" / "baseline.csv"
TELCO_HOLDOUT = DATA / "telco_churn" / "holdout.csv"

requires_telco = pytest.mark.skipif(
    not TELCO_BASELINE.exists(), reason="run scripts/prepare_datasets.py first"
)


class ConstantModel:
    """Always predicts the same class."""

    def __init__(self, value="yes"):
        self.value = value

    def predict(self, X):
        return np.array([self.value] * len(X))


class FirstColumnModel:
    """Predicts from the FIRST column only — detects column reordering."""

    def predict(self, X):
        values = np.asarray(X)[:, 0].astype(float)
        return np.where(values > 0, "high", "low")


class BrokenModel:
    def predict(self, X):
        raise RuntimeError("feature names mismatch")


class ShortModel:
    def predict(self, X):
        return np.array(["a"] * (len(X) - 1))


# ──────────────────────────────────────────────────────────────────────
# score_batch
# ──────────────────────────────────────────────────────────────────────


def test_score_batch_returns_one_prediction_per_row():
    batch = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    predictions = performance.score_batch(ConstantModel(), batch, ["a", "b"])
    assert len(predictions) == 3


def test_score_batch_enforces_column_order():
    """scikit-learn matches training columns by position, not by name.

    A batch whose columns arrive in a different order would feed every value to
    the wrong feature and return confident, silently wrong predictions. Selecting
    by the stored feature list is what prevents that.
    """
    batch = pd.DataFrame({"b": [-1.0, -2.0], "a": [10.0, 20.0]})
    predictions = performance.score_batch(FirstColumnModel(), batch, ["a", "b"])
    # 'a' holds positives, so selecting it first must give 'high'.
    assert list(predictions) == ["high", "high"]


def test_score_batch_rejects_missing_columns():
    batch = pd.DataFrame({"a": [1.0]})
    with pytest.raises(performance.ScoringError, match="missing required feature"):
        performance.score_batch(ConstantModel(), batch, ["a", "b"])


def test_score_batch_wraps_model_failures_with_context():
    batch = pd.DataFrame({"a": [1.0]})
    with pytest.raises(performance.ScoringError, match="model.predict\\(\\) failed"):
        performance.score_batch(BrokenModel(), batch, ["a"])


def test_score_batch_rejects_wrong_prediction_count():
    batch = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    with pytest.raises(performance.ScoringError, match="predictions"):
        performance.score_batch(ShortModel(), batch, ["a"])


# ──────────────────────────────────────────────────────────────────────
# prediction_distribution
# ──────────────────────────────────────────────────────────────────────


def test_prediction_distribution_counts_and_proportions():
    predictions = ["yes"] * 30 + ["no"] * 70
    distribution = performance.prediction_distribution(predictions)

    assert distribution["counts"] == {"yes": 30, "no": 70}
    assert distribution["proportions"]["yes"] == pytest.approx(0.30)
    assert distribution["total"] == 100


def test_unpredicted_classes_appear_as_zero():
    """A class vanishing from the output is a signal — it must be visible.

    Without this, a model that has collapsed to predicting one class shows a
    distribution containing a single entry, and nothing indicates the other
    class used to be there.
    """
    distribution = performance.prediction_distribution(
        ["yes"] * 50, labels=["yes", "no"]
    )
    assert distribution["counts"] == {"no": 0, "yes": 50}
    assert distribution["proportions"]["no"] == 0.0


def test_empty_predictions_do_not_divide_by_zero():
    distribution = performance.prediction_distribution([])
    assert distribution["total"] == 0
    assert distribution["proportions"] == {}


# ──────────────────────────────────────────────────────────────────────
# compute_metrics
# ──────────────────────────────────────────────────────────────────────


def test_perfect_predictions_score_one():
    y = ["a", "b", "a", "b"]
    metrics = performance.compute_metrics(y, y, positive_class="a")
    assert metrics["accuracy"] == 1.0
    assert metrics["error_rate"] == 0.0
    assert metrics["f1_macro"] == 1.0


def test_accuracy_and_error_rate_are_complements():
    y_true = ["a"] * 80 + ["b"] * 20
    y_pred = ["a"] * 100
    metrics = performance.compute_metrics(y_true, y_pred, positive_class="b")
    assert metrics["accuracy"] == pytest.approx(0.80)
    assert metrics["error_rate"] == pytest.approx(0.20)


def test_positive_class_and_macro_are_both_reported():
    """They disagree on imbalanced targets, which is the normal case here."""
    y_true = ["no"] * 90 + ["yes"] * 10
    y_pred = ["no"] * 95 + ["yes"] * 5

    metrics = performance.compute_metrics(y_true, y_pred, positive_class="yes")

    assert metrics["recall_positive"] is not None
    assert metrics["recall_macro"] is not None
    assert metrics["recall_positive"] != metrics["recall_macro"]
    assert metrics["positive_class"] == "yes"


def test_single_class_prediction_does_not_raise():
    """A model that has collapsed to one class is a real failure mode.

    It must be recorded with zeroed precision/recall, not crash the run.
    """
    y_true = ["a"] * 50 + ["b"] * 50
    y_pred = ["a"] * 100
    metrics = performance.compute_metrics(y_true, y_pred, positive_class="b")
    assert metrics["accuracy"] == pytest.approx(0.5)
    assert metrics["recall_positive"] == 0.0


def test_confusion_matrix_shape_and_labels():
    y_true = ["a", "a", "b", "b"]
    y_pred = ["a", "b", "b", "b"]
    matrix = performance.compute_metrics(y_true, y_pred)["confusion_matrix"]

    assert matrix["labels"] == ["a", "b"]
    assert matrix["matrix"] == [[1, 1], [0, 2]]


def test_multiclass_has_no_positive_class_metrics():
    y_true = ["a", "b", "c", "a"]
    y_pred = ["a", "b", "c", "c"]
    metrics = performance.compute_metrics(y_true, y_pred, positive_class="a")

    assert metrics["f1_macro"] is not None
    assert metrics["f1_positive"] is None, "binary averaging is undefined here"
    assert metrics["positive_class"] is None


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="length mismatch"):
        performance.compute_metrics(["a", "b"], ["a"])


# ──────────────────────────────────────────────────────────────────────
# FR-04.5 — the labels-absent contract
# ──────────────────────────────────────────────────────────────────────


def test_unavailable_metrics_are_none_never_zero():
    metrics = performance.unavailable_metrics(sample_count=500)

    for key in (
        "accuracy",
        "error_rate",
        "precision_macro",
        "recall_macro",
        "f1_macro",
        "precision_positive",
        "recall_positive",
        "f1_positive",
        "confusion_matrix",
    ):
        assert metrics[key] is None, f"{key} must be None, not {metrics[key]!r}"
    assert metrics["sample_count"] == 500


def test_evaluate_without_target_column_reports_no_labels():
    batch = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    block = performance.evaluate(ConstantModel(), batch, ["a"], target_column="label")

    assert block["labels_available"] is False
    assert block["accuracy"] is None
    assert block["prediction_distribution"]["total"] == 3, "predictions still computed"


def test_evaluate_with_an_entirely_empty_target_reports_no_labels():
    """A placeholder target column exported as blanks is not ground truth."""
    batch = pd.DataFrame({"a": [1.0, 2.0], "label": [np.nan, np.nan]})
    block = performance.evaluate(ConstantModel(), batch, ["a"], target_column="label")

    assert block["labels_available"] is False
    assert block["accuracy"] is None


def test_evaluate_with_labels_computes_metrics():
    batch = pd.DataFrame(
        {"a": [1.0, 2.0, 3.0, 4.0], "label": ["yes", "yes", "no", "yes"]}
    )
    block = performance.evaluate(
        ConstantModel("yes"), batch, ["a"], target_column="label", positive_class="yes"
    )

    assert block["labels_available"] is True
    assert block["accuracy"] == pytest.approx(0.75)
    assert block["confusion_matrix"] is not None


def test_evaluate_scores_only_the_labelled_rows():
    """Partially labelled batches are scored on the rows that have labels."""
    batch = pd.DataFrame(
        {"a": [1.0, 2.0, 3.0, 4.0], "label": ["yes", "yes", None, None]}
    )
    block = performance.evaluate(
        ConstantModel("yes"),
        batch,
        ["a"],
        target_column="label",
        # Always pass the model's known classes in production. Without them the
        # confusion matrix collapses to 1x1 on any batch where a class happens
        # to be absent, so its shape varies run to run and cannot be charted.
        labels=["no", "yes"],
    )

    assert block["labels_available"] is True
    assert block["accuracy"] == 1.0
    assert block["sample_count"] == 2
    assert block["prediction_distribution"]["total"] == 4, "all rows still predicted"
    assert len(block["confusion_matrix"]["labels"]) == 2, "shape stays stable"


# ──────────────────────────────────────────────────────────────────────
# Integration with a real scikit-learn Pipeline
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def telco_model():
    """A real Pipeline accepting raw columns — the PRD §4.3 model contract."""
    baseline = pd.read_csv(TELCO_BASELINE)
    schema = profiling.infer_schema(baseline, "Churn")
    features = profiling.feature_columns(schema)

    numeric = [c for c in features if schema[c]["type"] == "NUMERIC"]
    categorical = [c for c in features if schema[c]["type"] == "CATEGORICAL"]

    model = Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [
                        ("num", StandardScaler(), numeric),
                        ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
                    ]
                ),
            ),
            ("clf", RandomForestClassifier(n_estimators=50, random_state=42)),
        ]
    )
    model.fit(baseline[features], baseline["Churn"])
    return model, features


@requires_telco
def test_real_pipeline_scores_the_holdout(telco_model):
    model, features = telco_model
    holdout = pd.read_csv(TELCO_HOLDOUT)

    block = performance.evaluate(
        model,
        holdout,
        features,
        target_column="Churn",
        labels=["No", "Yes"],
        positive_class="Yes",
    )

    assert block["labels_available"] is True
    assert 0.70 < block["accuracy"] < 1.0
    assert block["precision_positive"] is not None
    assert set(block["prediction_distribution"]["counts"]) == {"No", "Yes"}


@requires_telco
def test_real_pipeline_handles_an_unlabelled_batch(telco_model):
    """The realistic production case: features arrive, ground truth does not."""
    model, features = telco_model
    holdout = pd.read_csv(TELCO_HOLDOUT).drop(columns=["Churn"])

    block = performance.evaluate(model, holdout, features, target_column="Churn")

    assert block["labels_available"] is False
    assert block["accuracy"] is None
    assert block["prediction_distribution"]["total"] == len(holdout)
