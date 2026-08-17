"""In-platform model training — synopsis §6.2 and the "Train Model" use case.

The client's college synopsis specifies that the system trains a supervised
model from historical data, evaluates baseline accuracy, precision and recall,
and then monitors it. This module provides that path.

One upload does the whole setup: the file is split into training and holdout
portions, a model is trained on the training portion, the trained artifact is
registered as a version, and the training portion becomes the baseline the
monitoring pipeline compares against. That last point matters — a model must be
monitored against the data it was actually trained on, so deriving both from one
file removes the commonest way to get that wrong.

Uploading a pre-trained artifact remains supported. This is an additional way in,
not a replacement.
"""

from __future__ import annotations

import io

import joblib
import pandas as pd
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

from core.constants import AuditAction, ValidationStatus, VersionStatus
from monitoring.engine import constants as C
from monitoring.engine import profiling

RANDOM_STATE = 42

# The algorithms the synopsis §6.2 names, plus Random Forest. Deliberately
# constrained: every one is CPU-only and trains in seconds on a laptop, which is
# what the resource requirements in §8 assume.
ALGORITHMS = {
    "logistic_regression": {
        "label": "Logistic Regression",
        "build": lambda: LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
        "note": "Fast, interpretable, a strong baseline for tabular problems.",
    },
    "decision_tree": {
        "label": "Decision Tree",
        "build": lambda: DecisionTreeClassifier(
            max_depth=8, min_samples_leaf=15, random_state=RANDOM_STATE
        ),
        "note": "Easy to explain; depth-capped so it generalises rather than memorises.",
    },
    "random_forest": {
        "label": "Random Forest",
        "build": lambda: RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_leaf=10,
            random_state=RANDOM_STATE,
        ),
        "note": "Usually the most accurate of the three; larger artifact.",
    },
    "balanced_random_forest": {
        "label": "Balanced Random Forest",
        "build": lambda: RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_leaf=10,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        ),
        "note": "Handles imbalanced targets — much better recall on the minority class.",
    },
}

MIN_TRAINING_ROWS = 100


def build_pipeline(estimator, numeric, categorical):
    """Wrap the estimator so the artifact accepts raw columns.

    This is what makes a trained model satisfy the PRD §4.3 upload contract: the
    preprocessing travels inside the artifact, so a monitoring batch can be
    scored straight from its CSV columns with no separate encoder to keep in
    step.
    """
    return Pipeline(
        [
            (
                "preprocess",
                ColumnTransformer(
                    [
                        ("numeric", StandardScaler(), numeric),
                        (
                            "categorical",
                            # Unseen categories must not raise. Drifting data
                            # introduces them by definition, and the platform's
                            # job is to score the batch and report the drift.
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                            categorical,
                        ),
                    ],
                    remainder="drop",
                ),
            ),
            ("classifier", estimator),
        ]
    )


@transaction.atomic
def train_and_register(
    ml_model,
    file_obj,
    algorithm_key,
    target_column,
    user=None,
    test_size=0.25,
    activate=True,
):
    """Train a model from an uploaded dataset and register it as a version.

    Returns ``(version, metrics)``. Raises :class:`ValidationError` with a
    message the upload form can display.
    """
    from datasets.services import create_baseline_dataset, read_csv
    from monitoring.services import compute_baseline_prediction_distribution
    from registry.models import ModelAuditLog, ModelVersion

    if algorithm_key not in ALGORITHMS:
        raise ValidationError(f"Unknown algorithm '{algorithm_key}'.")

    frame = read_csv(file_obj)

    if target_column not in frame.columns:
        raise ValidationError(
            f"Target column '{target_column}' is not in the file. "
            f"Columns found: {', '.join(frame.columns[:12])}"
        )
    if len(frame) < MIN_TRAINING_ROWS:
        raise ValidationError(
            f"Training needs at least {MIN_TRAINING_ROWS} rows; this file has {len(frame)}."
        )
    if frame[target_column].nunique(dropna=True) < 2:
        raise ValidationError(
            f"'{target_column}' has fewer than two distinct values, so there is "
            f"nothing for a classifier to learn."
        )

    frame = frame.dropna(subset=[target_column])
    schema = profiling.infer_schema(frame, target_column)
    features = profiling.feature_columns(schema)
    if not features:
        raise ValidationError(
            "No usable feature columns were found — every column was either the "
            "target or looked like an identifier."
        )

    numeric = [c for c in features if schema[c]["type"] == C.NUMERIC]
    categorical = [c for c in features if schema[c]["type"] == C.CATEGORICAL]

    # Stratify so both splits keep the target's class balance; without it a
    # rare class can land entirely on one side and the metrics become nonsense.
    train_df, test_df = train_test_split(
        frame,
        test_size=test_size,
        random_state=RANDOM_STATE,
        stratify=frame[target_column],
    )

    spec = ALGORITHMS[algorithm_key]
    pipeline = build_pipeline(spec["build"](), numeric, categorical)
    pipeline.fit(train_df[features], train_df[target_column])

    metrics = _evaluate(
        pipeline, test_df, features, target_column, ml_model.positive_class
    )

    buffer = io.BytesIO()
    joblib.dump(pipeline, buffer)
    artifact = ContentFile(buffer.getvalue())

    last = ml_model.versions.order_by("-version_number").first()
    number = (last.version_number + 1) if last else 1

    version = ModelVersion.objects.create(
        ml_model=ml_model,
        version_number=number,
        label=f"V{number}",
        artifact=artifact,
        status=VersionStatus.INACTIVE,
        validation_status=ValidationStatus.PASSED,
        validation_message="Trained in-platform; artifact is a Pipeline by construction.",
        algorithm_name=spec["label"],
        training_accuracy=metrics["accuracy"],
        file_size=len(buffer.getvalue()),
        changelog=(
            f"Trained in-platform on {len(train_df):,} rows using {spec['label']}. "
            f"Held-out accuracy {metrics['accuracy']:.4f}, "
            f"precision {metrics['precision']:.4f}, recall {metrics['recall']:.4f}."
        ),
        uploaded_by=user,
    )
    version.artifact.save(f"{ml_model.slug}_v{number}.joblib", artifact, save=True)

    # The training split becomes the baseline. A model must be monitored against
    # the data it was actually trained on — deriving both from one upload removes
    # the commonest way to get that wrong.
    baseline_csv = ContentFile(train_df.to_csv(index=False).encode())
    baseline_csv.name = f"{ml_model.slug}_baseline.csv"
    create_baseline_dataset(
        ml_model, version, baseline_csv, target_column=target_column, user=user
    )

    if activate:
        version.activate()
        version.refresh_from_db()
        compute_baseline_prediction_distribution(version)

    ModelAuditLog.objects.create(
        ml_model=ml_model,
        actor=user,
        action=AuditAction.VERSION_UPLOADED,
        details={
            "version": version.label,
            "algorithm": spec["label"],
            "trained_in_platform": True,
            "training_rows": len(train_df),
            "test_rows": len(test_df),
            **{k: round(v, 4) for k, v in metrics.items() if isinstance(v, float)},
        },
    )

    metrics["training_rows"] = len(train_df)
    metrics["test_rows"] = len(test_df)
    metrics["feature_count"] = len(features)
    metrics["algorithm"] = spec["label"]
    return version, metrics


def _evaluate(pipeline, test_df, features, target_column, positive_class):
    """Baseline accuracy, precision and recall — synopsis §6.2."""
    truth = test_df[target_column].astype(str)
    predictions = pd.Series(pipeline.predict(test_df[features])).astype(str)

    classes = sorted(truth.unique())
    positive = str(positive_class) if positive_class else None
    binary = len(classes) == 2 and positive in classes

    shared = (
        {"pos_label": positive, "average": "binary", "zero_division": 0}
        if binary
        else {"average": "macro", "zero_division": 0}
    )

    return {
        "accuracy": float(accuracy_score(truth, predictions)),
        "precision": float(precision_score(truth, predictions, **shared)),
        "recall": float(recall_score(truth, predictions, **shared)),
        "f1": float(f1_score(truth, predictions, **shared)),
        "averaging": "positive class" if binary else "macro",
    }
