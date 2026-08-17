"""Drift injection for the data feed simulator — PRD FR-05.7.

Builds each synthetic production batch by replaying held-out real rows and
applying transformations on top of them. Replay rather than synthesis is
deliberate: fully generated data looks fake, correlations between columns
collapse, and the statistics stop being interesting. Real rows with a controlled
shift applied look exactly like a production feed going bad, which is what the
demo needs to show.

Six transformations, matching the fixed set in TRD §4.6:

    numeric_shift        move a column's centre, in baseline standard deviations
    numeric_scale        widen or narrow its spread, leaving the centre alone
    category_shift       resample rows to hit target category proportions
    missing_injection    blank a fraction of a column
    duplicate_injection  repeat a fraction of the rows
    outlier_injection    push a fraction of values far past the baseline's fence

Shift sizes are expressed in **baseline standard deviations**, not raw units, so
a scenario reads the same regardless of the column's scale — and "+2σ" is
directly comparable to the drift thresholds the detector uses.

Every transformation takes an explicit ``rng``. Nothing here calls the global
random state, so a replayed scenario reproduces exactly (PRD NFR-14).

Pure Python. Imports no Django.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pandas as pd

# Where injected outliers land: this many IQRs past the baseline's upper
# quartile. Tukey's fence sits at 1.5, so 5.0 is unambiguously outside it and
# the data-quality module is guaranteed to flag the value.
OUTLIER_IQR_MULTIPLIER = 5.0

TRANSFORMATION_TYPES = (
    "numeric_shift",
    "numeric_scale",
    "category_shift",
    "missing_injection",
    "duplicate_injection",
    "outlier_injection",
)


class DriftPlanError(ValueError):
    """The drift plan is malformed or references something that does not exist."""


# ──────────────────────────────────────────────────────────────────────
# Baseline lookups
# ──────────────────────────────────────────────────────────────────────


def _summary(baseline_profile: dict[str, Any], column: str) -> dict[str, Any]:
    entry = baseline_profile.get("columns", {}).get(column)
    if entry is None:
        raise DriftPlanError(
            f"Column {column!r} is not monitored in the baseline profile"
        )
    return entry.get("summary", {})


# ──────────────────────────────────────────────────────────────────────
# The six transformations
# ──────────────────────────────────────────────────────────────────────


def numeric_shift(
    df: pd.DataFrame,
    column: str,
    mean_delta_sigma: float,
    baseline_profile: dict[str, Any],
    rng: np.random.Generator,
    fraction: float = 1.0,
) -> pd.DataFrame:
    """Move a column by `mean_delta_sigma` baseline standard deviations.

    ``fraction`` shifts only that share of the rows, chosen at random. It exists
    for two reasons.

    The realistic one: drift usually arrives in a segment rather than across the
    whole population — a new customer cohort, a price change on one plan — and a
    partial shift models that far better than moving every row in lockstep.

    The practical one: PSI is extremely sensitive to a bin emptying. Quantile
    bins are narrow wherever the baseline is dense, and on Telco's
    ``MonthlyCharges`` the lowest bin spans just 1.65 units. Shifting every row
    by even 0.05σ (1.5 units) empties it, and an emptied bin alone contributes
    about 0.69 to PSI — so a uniform shift is either invisible or immediately
    HIGH, with no moderate range in between. Shifting a fraction moves
    proportionally less mass and gives the fine control a graded demo needs.

    A constant baseline column has no standard deviation to scale by, so the
    shift is a no-op rather than pretending something happened.
    """
    std = _summary(baseline_profile, column).get("std")
    if not std:
        return df

    values = pd.to_numeric(df[column], errors="coerce")
    delta = mean_delta_sigma * std

    df = df.copy()
    if fraction >= 1.0:
        df[column] = values + delta
        return df

    count = int(round(len(df) * max(fraction, 0.0)))
    if count == 0:
        return df

    positions = rng.choice(len(df), size=count, replace=False)
    shifted = values.to_numpy(dtype=float, copy=True)
    shifted[positions] += delta
    df[column] = shifted
    return df


def numeric_scale(
    df: pd.DataFrame,
    column: str,
    std_multiplier: float,
    baseline_profile: dict[str, Any],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Widen (>1) or narrow (<1) a column's spread without moving its centre.

    Scaling is done around the *current* mean, not the baseline's, so this
    composes correctly with ``numeric_shift``: shifting then scaling widens the
    distribution where it now sits rather than dragging it back.
    """
    values = pd.to_numeric(df[column], errors="coerce")
    centre = values.mean()
    if pd.isna(centre):
        return df

    df = df.copy()
    df[column] = centre + (values - centre) * std_multiplier
    return df


def category_shift(
    df: pd.DataFrame,
    column: str,
    target_proportions: dict[str, float],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Resample whole rows so `column` hits the target category mix.

    Rows are resampled rather than the column being overwritten in place.
    Overwriting would break every correlation the column has with the rest of
    the row — a customer's contract type relates to their charges and tenure —
    and the resulting batch would be internally incoherent in a way real drift
    never is. Resampling means related columns drift together, which is what
    actually happens in production.

    Categories named in the plan but absent from the source rows cannot be
    sampled; their share is redistributed across the categories that do exist.
    """
    if not target_proportions:
        return df

    total = len(df)
    if total == 0:
        return df

    available = {
        category: group
        for category, group in df.groupby(df[column].astype(str), sort=False)
    }
    usable = {c: p for c, p in target_proportions.items() if c in available and p > 0}
    if not usable:
        return df

    weight_total = sum(usable.values())
    normalised = {c: p / weight_total for c, p in usable.items()}

    pieces = []
    for category, proportion in normalised.items():
        count = int(round(total * proportion))
        if count <= 0:
            continue
        source = available[category]
        indices = rng.choice(len(source), size=count, replace=True)
        pieces.append(source.iloc[indices])

    if not pieces:
        return df

    result = pd.concat(pieces, ignore_index=True)

    # Rounding can leave the batch a row or two off. Trim or top up so the
    # batch size the scenario asked for is the batch size it gets.
    if len(result) > total:
        keep = rng.choice(len(result), size=total, replace=False)
        result = result.iloc[keep]
    elif len(result) < total:
        extra = rng.choice(len(result), size=total - len(result), replace=True)
        result = pd.concat([result, result.iloc[extra]], ignore_index=True)

    return result.sample(
        frac=1.0, random_state=int(rng.integers(0, 2**31))
    ).reset_index(drop=True)


def missing_injection(
    df: pd.DataFrame, column: str, rate: float, rng: np.random.Generator
) -> pd.DataFrame:
    """Blank `rate` of the column's values."""
    if rate <= 0 or len(df) == 0:
        return df

    count = int(round(len(df) * min(rate, 1.0)))
    if count == 0:
        return df

    df = df.copy()
    positions = rng.choice(len(df), size=count, replace=False)
    df.iloc[positions, df.columns.get_loc(column)] = np.nan
    return df


def duplicate_injection(
    df: pd.DataFrame, rate: float, rng: np.random.Generator
) -> pd.DataFrame:
    """Append `rate` of the rows again, as exact duplicates.

    This grows the batch. That is correct — a feed that starts double-delivering
    records produces more rows, not the same number with some marked as copies.
    """
    if rate <= 0 or len(df) == 0:
        return df

    count = int(round(len(df) * rate))
    if count == 0:
        return df

    positions = rng.choice(len(df), size=count, replace=True)
    return pd.concat([df, df.iloc[positions]], ignore_index=True)


def outlier_injection(
    df: pd.DataFrame,
    column: str,
    rate: float,
    baseline_profile: dict[str, Any],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Push `rate` of the values far beyond the baseline's upper fence.

    The target sits at Q3 + 5·IQR, well outside Tukey's 1.5·IQR fence, so the
    data-quality module is guaranteed to count these rather than the test
    depending on where the fence happens to fall.

    A zero-IQR baseline column has no meaningful fence, so the fallback is five
    standard deviations above the maximum; if there is no spread at all either,
    the transformation is skipped.
    """
    if rate <= 0 or len(df) == 0:
        return df

    summary = _summary(baseline_profile, column)
    q1, q3 = summary.get("q1"), summary.get("q3")
    if q1 is None or q3 is None:
        return df

    iqr = q3 - q1
    if iqr > 0:
        target = q3 + OUTLIER_IQR_MULTIPLIER * iqr
    else:
        std, maximum = summary.get("std"), summary.get("max")
        if not std or maximum is None:
            return df
        target = maximum + 5.0 * std

    count = int(round(len(df) * min(rate, 1.0)))
    if count == 0:
        return df

    df = df.copy()
    positions = rng.choice(len(df), size=count, replace=False)
    df.iloc[positions, df.columns.get_loc(column)] = float(target)
    return df


# ──────────────────────────────────────────────────────────────────────
# Drift plans
# ──────────────────────────────────────────────────────────────────────


def validate_drift_plan(
    drift_plan: dict[str, Any], schema: dict[str, dict[str, Any]]
) -> None:
    """Check a plan before it is saved, not when a tick fails at 3am.

    A scenario that references a column which does not exist would otherwise run
    happily for ten batches and then raise inside the scheduler, where the only
    evidence is a log line.
    """
    phases = drift_plan.get("phases")
    if not isinstance(phases, list) or not phases:
        raise DriftPlanError("A drift plan needs a non-empty 'phases' list")

    seen_indices = set()
    for position, phase in enumerate(phases):
        if not isinstance(phase, dict):
            raise DriftPlanError(f"Phase {position} is not an object")

        from_batch = phase.get("from_batch")
        if not isinstance(from_batch, int) or from_batch < 0:
            raise DriftPlanError(
                f"Phase {position}: 'from_batch' must be a non-negative integer"
            )
        if from_batch in seen_indices:
            raise DriftPlanError(f"Two phases both start at batch {from_batch}")
        seen_indices.add(from_batch)

        for transformation in phase.get("transformations", []):
            kind = transformation.get("type")
            if kind not in TRANSFORMATION_TYPES:
                raise DriftPlanError(
                    f"Unknown transformation {kind!r}. "
                    f"Valid types: {', '.join(TRANSFORMATION_TYPES)}"
                )

            if kind == "duplicate_injection":
                continue  # operates on rows, names no column

            column = transformation.get("column")
            if not column:
                raise DriftPlanError(f"{kind} needs a 'column'")
            if column not in schema:
                raise DriftPlanError(f"{kind}: column {column!r} is not in the schema")
            if not schema[column].get("is_feature", True):
                raise DriftPlanError(
                    f"{kind}: column {column!r} is excluded from monitoring, so "
                    f"drifting it would have no visible effect"
                )


def resolve_phase(drift_plan: dict[str, Any], batch_index: int) -> dict[str, Any]:
    """The active phase for `batch_index`: the last one that has started.

    Phases are cumulative checkpoints rather than intervals — a plan with phases
    at batches 0, 10 and 25 means batch 30 uses the batch-25 phase, not nothing.
    """
    active: dict[str, Any] = {"from_batch": 0, "transformations": []}
    for phase in sorted(drift_plan.get("phases", []), key=lambda p: p["from_batch"]):
        if phase["from_batch"] <= batch_index:
            active = phase
        else:
            break
    return active


def apply_transformation(
    df: pd.DataFrame,
    transformation: dict[str, Any],
    baseline_profile: dict[str, Any],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Dispatch one transformation."""
    kind = transformation["type"]

    if kind == "numeric_shift":
        return numeric_shift(
            df,
            transformation["column"],
            float(transformation.get("mean_delta_sigma", 0.0)),
            baseline_profile,
            rng,
            fraction=float(transformation.get("fraction", 1.0)),
        )
    if kind == "numeric_scale":
        return numeric_scale(
            df,
            transformation["column"],
            float(transformation.get("std_multiplier", 1.0)),
            baseline_profile,
            rng,
        )
    if kind == "category_shift":
        return category_shift(
            df,
            transformation["column"],
            transformation.get("target_proportions", {}),
            rng,
        )
    if kind == "missing_injection":
        return missing_injection(
            df, transformation["column"], float(transformation.get("rate", 0.0)), rng
        )
    if kind == "duplicate_injection":
        return duplicate_injection(df, float(transformation.get("rate", 0.0)), rng)
    if kind == "outlier_injection":
        return outlier_injection(
            df,
            transformation["column"],
            float(transformation.get("rate", 0.0)),
            baseline_profile,
            rng,
        )

    raise DriftPlanError(f"Unknown transformation type {kind!r}")


def build_batch(
    holdout: pd.DataFrame,
    baseline_profile: dict[str, Any],
    drift_plan: dict[str, Any],
    batch_index: int,
    batch_size: int,
    *,
    include_labels: bool = True,
    target_column: str | None = None,
    base_seed: int = 42,
) -> pd.DataFrame:
    """Produce one simulated production batch.

    Seeded with ``base_seed + batch_index``, so every batch differs from the
    last but replaying a scenario from batch 0 reproduces the whole sequence
    exactly (PRD NFR-14) — which is what lets a demo be rehearsed.

    Transformations are applied in declaration order, so a plan can shift a
    column and then widen it, and the two compose predictably.
    """
    if holdout.empty:
        raise DriftPlanError("The holdout pool is empty — nothing to replay")

    rng = np.random.default_rng(base_seed + batch_index)

    # Sample WITHOUT replacement whenever the pool is big enough. Sampling with
    # replacement looks harmless but quietly manufactures duplicate rows: 600
    # draws from a 1,409-row pool repeat about 110 of them, and the data-quality
    # module correctly flags every one. The result is a "clean" phase that scores
    # 83 on quality before any fault has been injected — the simulator inventing
    # a problem the scenario never asked for.
    #
    # Replacement is only used when the batch is larger than the pool, where
    # repeating rows is unavoidable.
    replace = batch_size > len(holdout)
    positions = rng.choice(len(holdout), size=batch_size, replace=replace)
    batch = holdout.iloc[positions].reset_index(drop=True)

    phase = resolve_phase(drift_plan, batch_index)
    for transformation in phase.get("transformations", []):
        batch = apply_transformation(batch, transformation, baseline_profile, rng)

    if not include_labels and target_column and target_column in batch.columns:
        batch = batch.drop(columns=[target_column])

    return batch.reset_index(drop=True)


def describe_phase(phase: dict[str, Any]) -> str:
    """One-line summary of a phase, for the scenario screen and the run log."""
    transformations = phase.get("transformations", [])
    if not transformations:
        return "No drift — clean replay of held-out data"

    parts = []
    for transformation in transformations:
        kind = transformation["type"]
        column = transformation.get("column")
        if kind == "numeric_shift":
            parts.append(f"{column} shifted {transformation['mean_delta_sigma']:+g}σ")
        elif kind == "numeric_scale":
            parts.append(f"{column} spread ×{transformation['std_multiplier']:g}")
        elif kind == "category_shift":
            parts.append(f"{column} mix changed")
        elif kind == "missing_injection":
            parts.append(f"{column} {transformation['rate']:.0%} missing")
        elif kind == "duplicate_injection":
            parts.append(f"{transformation['rate']:.0%} duplicate rows")
        elif kind == "outlier_injection":
            parts.append(f"{column} {transformation['rate']:.0%} outliers")
    return " · ".join(parts)


def default_scenario(numeric_column: str, categorical_column: str) -> dict[str, Any]:
    """A three-phase plan producing the NONE → MODERATE → HIGH demo progression.

    Batches 0–9 are clean, so the dashboard establishes a healthy baseline before
    anything moves — a demo that starts already broken shows nothing.

    Phase 2 shifts **22%** of the rows rather than all of them, and that number
    is calibrated rather than guessed. Measured against the real detector on
    Telco ``MonthlyCharges`` at 2σ, over 15 consecutive batches:

        fraction 0.18  ->  PSI 0.078-0.139  flickers between NONE and MODERATE
        fraction 0.20  ->  PSI 0.110-0.168  MODERATE, but close to the 0.10 edge
        fraction 0.22  ->  PSI 0.134-0.194  MODERATE, clear of both bounds
        fraction 0.25  ->  PSI 0.173-0.250  MODERATE, brushing the 0.25 edge
        fraction 1.00  ->  PSI 5.68         straight to HIGH

    22% sits furthest from both band edges, so the amber phase stays amber for
    every batch instead of flickering red mid-demo. Shifting every row skips the
    moderate stage entirely — see ``numeric_shift`` for why PSI is this
    sensitive to a uniform shift.
    """
    return {
        "phases": [
            {"from_batch": 0, "transformations": []},
            {
                "from_batch": 10,
                "transformations": [
                    {
                        "type": "numeric_shift",
                        "column": numeric_column,
                        "mean_delta_sigma": 2.0,
                        "fraction": 0.22,
                    },
                    {
                        "type": "missing_injection",
                        "column": numeric_column,
                        "rate": 0.03,
                    },
                ],
            },
            {
                "from_batch": 25,
                "transformations": [
                    {
                        "type": "numeric_shift",
                        "column": numeric_column,
                        "mean_delta_sigma": 2.2,
                        "fraction": 1.0,
                    },
                    {
                        "type": "numeric_scale",
                        "column": numeric_column,
                        "std_multiplier": 1.4,
                    },
                    {
                        "type": "category_shift",
                        "column": categorical_column,
                        "target_proportions": {},  # filled in per dataset
                    },
                    {
                        "type": "outlier_injection",
                        "column": numeric_column,
                        "rate": 0.04,
                    },
                    {"type": "duplicate_injection", "rate": 0.05},
                ],
            },
        ]
    }


def copy_plan(drift_plan: dict[str, Any]) -> dict[str, Any]:
    """Deep copy, so editing a scenario never mutates a stored plan in place."""
    return copy.deepcopy(drift_plan)
