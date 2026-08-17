"""The monitoring pipeline — the engine's single entry point.

Every ingestion path in the application converges here: CSV upload, the
scheduled simulator, and the REST endpoint all end up calling
``run_monitoring()`` with a DataFrame. Adding a fourth way to get data in means
adding a caller, never a second pipeline.

Five stages, in this order:

    1. quality      is the incoming data clean?
    2. drift        does it still look like the training data?
    3. performance  is the model still right?
    4. health       one number combining all of the above
    5. explain      say all of that in English

Ordering is deliberate. Quality runs first because its findings — unseen
categories, missing-value spikes — provide context for reading the drift
results that follow.

Takes DataFrames and dicts, returns a dict. Imports no Django, touches no
database, opens no network connection (BACKEND_FLOW.md §1), which is what makes
the whole thing demonstrable in a notebook.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from . import constants as C
from . import drift, explain, health, performance, profiling, quality


def summarise_statuses(results: list[dict[str, Any]]) -> dict[str, int]:
    """Count features by drift status.

    These counts are denormalised onto the run record so list views and charts
    never have to aggregate the per-feature table.
    """
    counts = {
        "high": 0,
        "moderate": 0,
        "none": 0,
        "insufficient": 0,
        "total": len(results),
    }
    key = {
        C.HIGH: "high",
        C.MODERATE: "moderate",
        C.NONE: "none",
        C.INSUFFICIENT_DATA: "insufficient",
    }
    for result in results:
        counts[key[result["status"]]] += 1
    return counts


def run_monitoring(
    batch_df: pd.DataFrame,
    baseline_profile: dict[str, Any],
    reference_sample: pd.DataFrame,
    schema: dict[str, dict[str, Any]],
    model,
    *,
    thresholds: dict[str, float] | None = None,
    baseline_prediction_distribution: dict[str, float] | None = None,
    reference_accuracy: float | None = None,
    target_column: str | None = None,
    class_labels: list | None = None,
    positive_class: Any = None,
) -> dict[str, Any]:
    """Run the full monitoring cycle over one batch.

    Args:
        batch_df: the arriving production rows.
        baseline_profile: the stored profile from the baseline dataset.
        reference_sample: raw baseline rows, for the K-S test — which needs
            samples rather than bins.
        schema: the baseline schema; decides which columns are monitored.
        model: a loaded scikit-learn estimator or Pipeline.
        thresholds: resolved per-model thresholds. Defaults to the engine's own.
        baseline_prediction_distribution: the class mix the model produced on
            the baseline, computed once at version activation.
        reference_accuracy: the version's training accuracy, or its first
            labelled run's accuracy. ``None`` on a first run.
        target_column: name of the label column, if the batch has one.
        class_labels: every class the model knows. Always pass this — without
            it the confusion matrix collapses to 1x1 on any batch missing a
            class, so its shape varies run to run and cannot be charted.
        positive_class: the class of interest for binary problems.

    Returns:
        A nested dict with ``quality``, ``drift``, ``performance``, ``health``
        and ``meta`` keys, ready to be persisted by the Django layer.

    Raises:
        performance.ScoringError: if the model cannot score the batch. The
            caller marks the run FAILED and raises a RUN_FAILED alert
            (BACKEND_FLOW.md §4.3). A model that cannot predict is a real
            failure, not a partial result.
    """
    started = time.perf_counter()
    thresholds = thresholds or drift.default_thresholds()

    # ── 1. quality ────────────────────────────────────────────────────
    quality_report = quality.assess(batch_df, baseline_profile, schema)

    # ── 2. drift ──────────────────────────────────────────────────────
    drift_results = drift.analyse_features(
        baseline_profile, reference_sample, batch_df, schema, thresholds
    )
    overall_status = drift.rollup(drift_results, thresholds)
    counts = summarise_statuses(drift_results)

    # ── 3. performance ────────────────────────────────────────────────
    feature_list = profiling.feature_columns(schema)
    performance_block = performance.evaluate(
        model,
        batch_df,
        feature_list,
        target_column=target_column,
        labels=class_labels,
        positive_class=positive_class,
    )

    # ── 4. health ─────────────────────────────────────────────────────
    health_block = health.compute(
        current_accuracy=performance_block["accuracy"],
        reference_accuracy=reference_accuracy,
        high_count=counts["high"],
        moderate_count=counts["moderate"],
        quality_score=quality_report["quality_score"],
        baseline_prediction_distribution=baseline_prediction_distribution,
        current_prediction_distribution=performance_block["prediction_distribution"][
            "proportions"
        ],
        labels_available=performance_block["labels_available"],
        overall_drift_status=overall_status,
    )

    # ── 5. explain ────────────────────────────────────────────────────
    explained = explain.explain_all(drift_results, thresholds)

    return {
        "quality": quality_report,
        "drift": {
            "features": explained,
            "overall_status": overall_status,
            "counts": counts,
        },
        "performance": performance_block,
        "health": health_block,
        "meta": {
            "row_count": int(len(batch_df)),
            "features_monitored": len(feature_list),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "thresholds": dict(thresholds),
        },
    }
