"""Model performance monitoring — PRD FR-04.

Every batch is scored by the model, always. What happens next depends on whether
the batch carried the true labels:

    labels present   accuracy, precision, recall, F1, error rate, confusion matrix
    labels absent    prediction distribution only

The rule that matters is FR-04.5: **when labels are absent the metrics are
``None``, never ``0``.** A batch with no ground truth has not scored zero
accuracy — accuracy is simply unknown. Storing 0 would drag every average down,
turn every performance chart into a cliff, and fire alerts about a model that is
fine. Real production data usually has no labels yet, so this is the common case,
not the edge case.

Pure Python. Imports no Django (BACKEND_FLOW.md §1).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)


class ScoringError(RuntimeError):
    """The model could not score the batch.

    Raised with the underlying cause attached so the run can be marked FAILED
    with a message a human can act on, rather than a bare traceback.
    """


def score_batch(
    model, batch_df: pd.DataFrame, feature_columns: list[str]
) -> np.ndarray:
    """Run the model over the batch and return its predictions.

    Columns are selected and ordered explicitly. scikit-learn matches training
    columns by position, not by name, so a batch whose columns arrive in a
    different order would produce silently wrong predictions — every value fed
    to the wrong feature, with no error raised.
    """
    missing = [c for c in feature_columns if c not in batch_df.columns]
    if missing:
        raise ScoringError(f"Batch is missing required feature columns: {missing}")

    features = batch_df[feature_columns]

    try:
        predictions = model.predict(features)
    except Exception as exc:  # noqa: BLE001 - re-raised with context below
        raise ScoringError(f"model.predict() failed: {exc}") from exc

    predictions = np.asarray(predictions)
    if predictions.shape[0] != len(batch_df):
        raise ScoringError(
            f"Model returned {predictions.shape[0]} predictions "
            f"for {len(batch_df)} rows"
        )
    return predictions


def prediction_distribution(predictions, labels: list | None = None) -> dict[str, Any]:
    """Counts and proportions per predicted class.

    Computed for every run regardless of labels (FR-04.2). It is the only
    performance signal available on unlabelled data, and it feeds the health
    score's stability component.
    """
    series = pd.Series(np.asarray(predictions)).astype(str)
    counts = series.value_counts()

    if labels is not None:
        # Include classes the model did not predict at all this batch, as zeros.
        # A class disappearing from the output is a signal, and it can only be
        # seen if the class is present in the distribution.
        for label in labels:
            key = str(label)
            if key not in counts.index:
                counts[key] = 0
        counts = counts.reindex(sorted(counts.index, key=str))

    total = int(counts.sum())
    return {
        "counts": {str(k): int(v) for k, v in counts.items()},
        "proportions": (
            {str(k): float(v / total) for k, v in counts.items()} if total else {}
        ),
        "total": total,
    }


def compute_metrics(
    y_true,
    y_pred,
    labels: list | None = None,
    positive_class: Any = None,
) -> dict[str, Any]:
    """Classification metrics for a labelled batch.

    Both positive-class and macro averages are computed and stored (FR-04.4).
    They answer different questions and disagree in exactly the case that matters
    — an imbalanced target, which is what churn and income both are. Macro
    treats both classes equally; positive-class reports on the class anyone
    actually cares about.

    ``zero_division=0`` keeps a batch in which the model predicted only one class
    from raising. That is a real thing a drifting model does, and it must be
    recorded rather than crashing the run.
    """
    y_true = np.asarray(y_true).astype(str)
    y_pred = np.asarray(y_pred).astype(str)

    if y_true.shape[0] != y_pred.shape[0]:
        raise ValueError(
            f"Label/prediction length mismatch: {y_true.shape[0]} vs {y_pred.shape[0]}"
        )

    if labels is None:
        class_labels = sorted(set(y_true) | set(y_pred))
    else:
        class_labels = [str(label) for label in labels]

    accuracy = float(accuracy_score(y_true, y_pred))

    metrics: dict[str, Any] = {
        "accuracy": accuracy,
        "error_rate": float(1.0 - accuracy),
        "precision_macro": float(
            precision_score(
                y_true, y_pred, labels=class_labels, average="macro", zero_division=0
            )
        ),
        "recall_macro": float(
            recall_score(
                y_true, y_pred, labels=class_labels, average="macro", zero_division=0
            )
        ),
        "f1_macro": float(
            f1_score(
                y_true, y_pred, labels=class_labels, average="macro", zero_division=0
            )
        ),
        "confusion_matrix": {
            "labels": class_labels,
            "matrix": confusion_matrix(y_true, y_pred, labels=class_labels).tolist(),
        },
        "sample_count": int(y_true.shape[0]),
    }

    if positive_class is not None:
        positive = str(positive_class)
        shared = dict(
            labels=class_labels, pos_label=positive, average="binary", zero_division=0
        )
        if len(class_labels) == 2 and positive in class_labels:
            metrics["precision_positive"] = float(
                precision_score(y_true, y_pred, **shared)
            )
            metrics["recall_positive"] = float(recall_score(y_true, y_pred, **shared))
            metrics["f1_positive"] = float(f1_score(y_true, y_pred, **shared))
            metrics["positive_class"] = positive
        else:
            # Multiclass, or a positive class that is not present. Binary
            # averaging is undefined; the macro figures above still apply.
            metrics["precision_positive"] = None
            metrics["recall_positive"] = None
            metrics["f1_positive"] = None
            metrics["positive_class"] = None
    else:
        metrics["precision_positive"] = None
        metrics["recall_positive"] = None
        metrics["f1_positive"] = None
        metrics["positive_class"] = None

    return metrics


def unavailable_metrics(sample_count: int) -> dict[str, Any]:
    """The metric block for an unlabelled batch.

    Every metric is explicitly ``None``. This function exists so that "no
    labels" is written in exactly one place and cannot drift into zeros by
    accident somewhere down the line.
    """
    return {
        "accuracy": None,
        "error_rate": None,
        "precision_macro": None,
        "recall_macro": None,
        "f1_macro": None,
        "precision_positive": None,
        "recall_positive": None,
        "f1_positive": None,
        "positive_class": None,
        "confusion_matrix": None,
        "sample_count": sample_count,
    }


def evaluate(
    model,
    batch_df: pd.DataFrame,
    feature_columns: list[str],
    target_column: str | None = None,
    labels: list | None = None,
    positive_class: Any = None,
) -> dict[str, Any]:
    """Score a batch and produce the full performance block.

    ``labels_available`` is decided here, once: the target column must be named,
    present in the batch, and hold at least one non-null value. A target column
    that is present but entirely empty is treated as absent — which is what a
    system exporting a placeholder column produces.
    """
    predictions = score_batch(model, batch_df, feature_columns)

    has_labels = (
        target_column is not None
        and target_column in batch_df.columns
        and bool(batch_df[target_column].notna().any())
    )

    block: dict[str, Any] = {
        "labels_available": has_labels,
        "prediction_distribution": prediction_distribution(predictions, labels),
    }

    if not has_labels:
        block.update(unavailable_metrics(int(len(batch_df))))
        return block

    labelled = batch_df[target_column].notna().to_numpy()
    block.update(
        compute_metrics(
            batch_df.loc[labelled, target_column],
            predictions[labelled],
            labels=labels,
            positive_class=positive_class,
        )
    )
    return block
