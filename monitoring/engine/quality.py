"""Data quality monitoring — PRD FR-11.

Six checks on every incoming batch, all measured against the *baseline*:

    missing values      per column and overall
    duplicate records   exact duplicate rows
    invalid values      outside the baseline's observed range
    unseen categories   category values the baseline never contained
    outliers            IQR rule using the baseline's quartiles
    type mismatches     column no longer holds the kind of data it used to

The recurring principle: **every threshold comes from the baseline, never from
the batch.** Computing IQR bounds from the batch itself would define the drift
away — a batch where every value has doubled has perfectly normal quartiles
relative to itself.

Pure Python. Imports no Django (BACKEND_FLOW.md §1).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import constants as C

# Tukey's fence. 1.5 x IQR is the convention behind every boxplot.
IQR_MULTIPLIER = 1.5


def default_quality_weights() -> dict[str, float]:
    """Penalty weights and caps from PRD §8.5."""
    return {
        "missing_rate": 1.5,
        "missing_cap": 30.0,
        "duplicate_rate": 1.0,
        "duplicate_cap": 20.0,
        "type_mismatch_per_column": 10.0,
        "type_mismatch_cap": 20.0,
        "unseen_category_per_column": 3.0,
        "unseen_category_cap": 15.0,
        "outlier_rate": 0.5,
        "outlier_cap": 15.0,
    }


def _dtype_kind(dtype: str) -> str:
    """Collapse a pandas dtype to the only distinction that matters here.

    Comparing exact dtype strings produces constant false alarms: a column read
    as int64 in the baseline arrives as float64 the moment one row is missing,
    and that is normal CSV behaviour, not a data quality problem. What genuinely
    matters is a column that held numbers now holding text.
    """
    lowered = dtype.lower()
    if lowered.startswith("bool"):
        return "boolean"
    if any(lowered.startswith(p) for p in ("int", "uint", "float", "complex")):
        return "numeric"
    if "datetime" in lowered or "timedelta" in lowered:
        return "temporal"
    return "text"


def assess(
    batch_df: pd.DataFrame,
    baseline_profile: dict[str, Any],
    schema: dict[str, dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run every quality check and return one report.

    Only monitored features are checked. Excluded columns and the target are
    skipped — a missing value in an excluded ID column is not a quality problem
    the model cares about.
    """
    weights = weights or default_quality_weights()
    profile_columns = baseline_profile.get("columns", {})

    monitored = [
        column
        for column in profile_columns
        if column in batch_df.columns and schema.get(column, {}).get("is_feature", True)
    ]

    row_count = int(len(batch_df))
    per_column: dict[str, dict[str, Any]] = {}

    missing_cells = 0
    outlier_cells = 0
    numeric_cells = 0

    type_mismatch_columns: dict[str, dict[str, str]] = {}
    unseen_category_columns: dict[str, list[str]] = {}
    out_of_range_columns: dict[str, dict[str, Any]] = {}
    outlier_counts: dict[str, dict[str, Any]] = {}

    for column in monitored:
        entry = profile_columns[column]
        series = batch_df[column]
        summary = entry["summary"]

        missing = int(series.isna().sum())
        missing_cells += missing

        column_report: dict[str, Any] = {
            "type": entry["type"],
            "missing": missing,
            "missing_pct": round(100.0 * missing / row_count, 4) if row_count else 0.0,
        }

        # ── type mismatch ────────────────────────────────────────────
        expected_kind = _dtype_kind(schema.get(column, {}).get("dtype", ""))
        actual_kind = _dtype_kind(str(series.dtype))
        if expected_kind != actual_kind:
            type_mismatch_columns[column] = {
                "expected": expected_kind,
                "actual": actual_kind,
            }
            column_report["type_mismatch"] = True

        if entry["type"] == C.NUMERIC:
            values = pd.to_numeric(series, errors="coerce").dropna()
            numeric_cells += int(values.size)

            # ── invalid values: outside the baseline's observed range ──
            baseline_min, baseline_max = summary.get("min"), summary.get("max")
            if baseline_min is not None and baseline_max is not None and values.size:
                below = int((values < baseline_min).sum())
                above = int((values > baseline_max).sum())
                if below or above:
                    out_of_range_columns[column] = {
                        "count": below + above,
                        "pct": round(100.0 * (below + above) / values.size, 4),
                        "below_min": below,
                        "above_max": above,
                        "baseline_min": baseline_min,
                        "baseline_max": baseline_max,
                    }
                column_report["out_of_range"] = below + above

            # ── outliers: IQR fence from the BASELINE quartiles ────────
            q1, q3 = summary.get("q1"), summary.get("q3")
            if q1 is not None and q3 is not None and values.size:
                iqr = q3 - q1
                lower = q1 - IQR_MULTIPLIER * iqr
                upper = q3 + IQR_MULTIPLIER * iqr
                count = int(((values < lower) | (values > upper)).sum())
                outlier_cells += count
                if count:
                    outlier_counts[column] = {
                        "count": count,
                        "pct": round(100.0 * count / values.size, 4),
                        "lower_fence": float(lower),
                        "upper_fence": float(upper),
                    }
                column_report["outliers"] = count

        else:
            # ── unseen categories ─────────────────────────────────────
            baseline_categories = set(map(str, entry.get("categories", {})))
            present = set(series.dropna().astype(str).unique())
            unseen = sorted(present - baseline_categories)
            if unseen:
                unseen_category_columns[column] = unseen
            column_report["unseen_categories"] = unseen

        per_column[column] = column_report

    # ── duplicates ────────────────────────────────────────────────────
    duplicate_rows = int(batch_df.duplicated().sum()) if row_count else 0

    # ── aggregate rates ───────────────────────────────────────────────
    total_cells = row_count * len(monitored)
    missing_pct = round(100.0 * missing_cells / total_cells, 4) if total_cells else 0.0
    duplicate_pct = round(100.0 * duplicate_rows / row_count, 4) if row_count else 0.0
    outlier_pct = (
        round(100.0 * outlier_cells / numeric_cells, 4) if numeric_cells else 0.0
    )

    penalties = {
        "missing": min(weights["missing_cap"], missing_pct * weights["missing_rate"]),
        "duplicates": min(
            weights["duplicate_cap"], duplicate_pct * weights["duplicate_rate"]
        ),
        "type_mismatches": min(
            weights["type_mismatch_cap"],
            weights["type_mismatch_per_column"] * len(type_mismatch_columns),
        ),
        "unseen_categories": min(
            weights["unseen_category_cap"],
            weights["unseen_category_per_column"] * len(unseen_category_columns),
        ),
        "outliers": min(weights["outlier_cap"], outlier_pct * weights["outlier_rate"]),
    }
    quality_score = max(0.0, 100.0 - sum(penalties.values()))

    return {
        "row_count": row_count,
        "columns_checked": len(monitored),
        "missing_total": missing_cells,
        "missing_pct": missing_pct,
        "duplicate_rows": duplicate_rows,
        "duplicate_pct": duplicate_pct,
        "type_mismatch_columns": type_mismatch_columns,
        "unseen_category_columns": unseen_category_columns,
        "out_of_range_columns": out_of_range_columns,
        "outlier_counts": outlier_counts,
        "outlier_pct": outlier_pct,
        "penalties": {k: round(v, 4) for k, v in penalties.items()},
        "quality_score": int(round(quality_score)),
        "per_column": per_column,
    }
