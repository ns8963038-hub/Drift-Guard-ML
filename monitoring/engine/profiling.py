"""Schema inference and baseline profiling.

A *profile* is the compressed statistical fingerprint of a dataset: per-column
bin edges, bin counts, category frequencies and summary statistics. It is
computed once when a baseline dataset is uploaded, stored as JSON, and reused by
every monitoring run thereafter — so no run ever re-reads the training data.

The critical rule in this module: **batches are binned using the baseline's
edges, never their own.** Recomputing edges per batch would rescale the very
shift we are trying to measure and hide all drift.

Pure Python. Imports no Django (BACKEND_FLOW.md §1).
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from . import constants as C

# Column names that are almost certainly identifiers rather than features.
_ID_NAME_PATTERN = re.compile(
    r"(^id$|_id$|^id_|id$|uuid|guid|^key$|_key$|^index$|serial|^no$|number$)",
    re.IGNORECASE,
)


# ──────────────────────────────────────────────────────────────────────
# Schema inference
# ──────────────────────────────────────────────────────────────────────


def classify_column(series: pd.Series) -> str:
    """Return NUMERIC or CATEGORICAL for one column.

    Numeric dtype alone is not enough. A 0/1 flag stored as int64 is categorical
    in every way that matters, and running a K-S test on it produces a number
    that means nothing. The cardinality check is what separates the two.
    """
    if not pd.api.types.is_numeric_dtype(series):
        return C.CATEGORICAL
    if pd.api.types.is_bool_dtype(series):
        return C.CATEGORICAL
    if series.nunique(dropna=True) <= C.MAX_UNIQUE_FOR_CATEGORICAL:
        return C.CATEGORICAL
    return C.NUMERIC


def suggest_exclusion(series: pd.Series, column: str) -> str | None:
    """Return a reason to exclude this column from drift monitoring, or None.

    These are suggestions only. The user confirms or overrides every one of them
    on the baseline upload screen (PRD FR-08.4), because the heuristic cannot
    know that, say, ``area_code`` is a real feature.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return "Timestamp column — drift on a timestamp is not meaningful"

    non_null = series.dropna()
    if len(non_null) == 0:
        return "Column is entirely empty"

    if non_null.nunique() == 1:
        return "Constant column — one distinct value, so it cannot drift"

    # A column that is unique for (nearly) every row identifies rows rather than
    # describing them. 99% rather than 100% tolerates a handful of duplicates.
    if non_null.nunique() >= 0.99 * len(non_null) and not pd.api.types.is_float_dtype(
        series
    ):
        return "Appears to be an identifier — one distinct value per row"

    if _ID_NAME_PATTERN.search(column):
        return "Column name looks like an identifier"

    return None


def infer_schema(df: pd.DataFrame, target_column: str) -> dict[str, dict[str, Any]]:
    """Build the schema for a baseline dataset.

    Returns one entry per column::

        {
          "MonthlyCharges": {
            "dtype": "float64",
            "type": "NUMERIC",
            "is_target": False,
            "is_feature": True,
            "excluded": False,
            "exclusion_reason": None,
          },
          ...
        }

    ``is_feature`` is the field the rest of the engine reads: it means "monitor
    this column and feed it to the model".
    """
    if target_column not in df.columns:
        raise ValueError(
            f"Target column {target_column!r} is not present. "
            f"Available columns: {', '.join(df.columns)}"
        )

    schema: dict[str, dict[str, Any]] = {}
    for column in df.columns:
        series = df[column]
        is_target = column == target_column
        reason = None if is_target else suggest_exclusion(series, column)

        schema[column] = {
            "dtype": str(series.dtype),
            "type": classify_column(series),
            "is_target": is_target,
            "is_feature": not is_target and reason is None,
            "excluded": reason is not None,
            "exclusion_reason": reason,
        }
    return schema


def feature_columns(schema: dict[str, dict[str, Any]]) -> list[str]:
    """The columns that are monitored and passed to the model, in schema order."""
    return [name for name, spec in schema.items() if spec["is_feature"]]


def target_column(schema: dict[str, dict[str, Any]]) -> str | None:
    for name, spec in schema.items():
        if spec["is_target"]:
            return name
    return None


# ──────────────────────────────────────────────────────────────────────
# Binning
# ──────────────────────────────────────────────────────────────────────


def build_bin_edges(values: np.ndarray, bins: int = C.DEFAULT_BIN_COUNT) -> list[float]:
    """Quantile-based bin edges for a numeric column.

    Quantile bins rather than equal-width bins because real features are skewed:
    equal-width bins on a long-tailed column put 95% of the mass in bin 0, and
    PSI computed over that is close to meaningless.

    Duplicate edges are collapsed. A column where more than 1/bins of the values
    are identical (very common — zeros, floors, caps) produces repeated
    quantiles, and passing those to ``np.histogram`` raises.

    A degenerate column (fewer than two distinct values) returns ``[v, v]``,
    which callers treat as a single bin holding everything.
    """
    clean = values[~pd.isna(values)].astype(float)
    if clean.size == 0:
        return []

    quantiles = np.linspace(0.0, 1.0, bins + 1)
    edges = np.unique(np.quantile(clean, quantiles))

    if edges.size < 2:
        value = float(edges[0]) if edges.size else 0.0
        return [value, value]

    return [float(edge) for edge in edges]


def bin_counts(values: np.ndarray, edges: list[float]) -> list[int]:
    """Count values into `edges`, which came from the baseline.

    The outer edges are widened to ±inf before counting. Without this, batch
    values beyond the baseline's observed range fall outside every bin and are
    silently dropped — so the proportions would no longer sum to 1 and PSI would
    quietly understate the drift. Out-of-range values are exactly the ones we
    most want counted.
    """
    clean = values[~pd.isna(values)].astype(float)
    if clean.size == 0 or len(edges) < 2:
        return [0] * max(len(edges) - 1, 1)

    if edges[0] == edges[-1]:  # degenerate column: one bin, everything in it
        return [int(clean.size)]

    open_edges = np.array(edges, dtype=float)
    open_edges[0] = -np.inf
    open_edges[-1] = np.inf

    counts, _ = np.histogram(clean, bins=open_edges)
    return [int(count) for count in counts]


# ──────────────────────────────────────────────────────────────────────
# Column summaries
# ──────────────────────────────────────────────────────────────────────


def summarise_numeric(series: pd.Series) -> dict[str, Any]:
    """Summary statistics used by the drift explanations (PRD FR-14.3)."""
    clean = series.dropna().astype(float)
    total = int(len(series))
    missing = total - int(len(clean))

    if clean.empty:
        return {
            "count": 0,
            "missing": missing,
            "missing_pct": 100.0 if total else 0.0,
            "mean": None,
            "std": None,
            "min": None,
            "q1": None,
            "median": None,
            "q3": None,
            "max": None,
        }

    return {
        "count": int(clean.size),
        "missing": missing,
        "missing_pct": round(100.0 * missing / total, 4) if total else 0.0,
        "mean": float(clean.mean()),
        # ddof=0 keeps std defined for a single-row batch, where the sample
        # standard deviation would be NaN.
        "std": float(clean.std(ddof=0)),
        "min": float(clean.min()),
        "q1": float(clean.quantile(0.25)),
        "median": float(clean.median()),
        "q3": float(clean.quantile(0.75)),
        "max": float(clean.max()),
    }


def summarise_categorical(series: pd.Series) -> dict[str, Any]:
    """Category counts and proportions, ordered most frequent first."""
    total = int(len(series))
    clean = series.dropna()
    missing = total - int(len(clean))

    counts = clean.astype(str).value_counts()
    observed = int(counts.sum())

    return {
        "count": int(len(clean)),
        "missing": missing,
        "missing_pct": round(100.0 * missing / total, 4) if total else 0.0,
        "n_unique": int(counts.size),
        "categories": {str(k): int(v) for k, v in counts.items()},
        "proportions": (
            {str(k): float(v / observed) for k, v in counts.items()} if observed else {}
        ),
    }


def summarise_column(series: pd.Series, column_type: str) -> dict[str, Any]:
    """Dispatch to the numeric or categorical summariser."""
    if column_type == C.NUMERIC:
        return summarise_numeric(series)
    return summarise_categorical(series)


# ──────────────────────────────────────────────────────────────────────
# Profile
# ──────────────────────────────────────────────────────────────────────


def build_profile(
    df: pd.DataFrame, schema: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Build the stored baseline profile.

    Only monitored features are profiled — excluded columns and the target are
    skipped, since nothing downstream reads them.

    The result is JSON-serialisable with no custom encoder: every value is a
    Python ``int``, ``float``, ``str``, ``bool``, ``None``, list or dict. NumPy
    scalars are cast at the boundary, because ``json.dumps`` cannot serialise
    ``np.int64`` and the failure would not surface until a real upload.
    """
    columns: dict[str, Any] = {}

    for column, spec in schema.items():
        if not spec["is_feature"]:
            continue

        series = df[column]
        summary = summarise_column(series, spec["type"])
        entry: dict[str, Any] = {"type": spec["type"], "summary": summary}

        if spec["type"] == C.NUMERIC:
            edges = build_bin_edges(series.to_numpy())
            entry["bin_edges"] = edges
            entry["bin_counts"] = bin_counts(series.to_numpy(), edges)
        else:
            entry["categories"] = summary["categories"]

        columns[column] = entry

    return {
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "feature_count": len(columns),
        "columns": columns,
    }
