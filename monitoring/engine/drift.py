"""Data drift detection — the core of the project.

Four measures per feature, each answering a different question:

    K-S test      (numeric)      Are these two samples from the same distribution?
    Chi-Square    (categorical)  Are these category frequencies independent of which
                                 dataset they came from?
    PSI                          How far has the distribution moved? (industry standard)
    JSD                          How far has the distribution moved? (information theory)

The tests give **significance**; PSI and JSD give **magnitude**. Both are needed,
because neither is trustworthy alone:

  * On a 50,000-row batch a K-S test returns p < 0.001 for a shift far too small
    to matter. Significance alone would flag every batch as drifted.
  * On a 40-row batch PSI can look alarming from pure sampling noise. Magnitude
    alone would flag noise as drift.

So magnitude decides the band, and significance only gates it (PRD §7.3).

Pure Python. Imports no Django (BACKEND_FLOW.md §1).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from . import constants as C
from . import profiling

# Proportions are smoothed by this before any ratio or logarithm is taken.
# PSI divides by the baseline proportion; an empty bin would make it infinite.
EPSILON = 1e-4

# Both sides of the K-S test are capped at this many values. Bounds the runtime
# on large batches and, with a fixed seed, keeps results reproducible (NFR-14).
MAX_TEST_SAMPLE = 50_000
SAMPLE_SEED = 42

# Chi-Square is unreliable when an expected cell count falls below this.
MIN_EXPECTED_FREQUENCY = 5
OTHER_CATEGORY = "__OTHER__"


def default_thresholds() -> dict[str, float]:
    """Engine-side defaults, matching PRD §7.2 and §7.4.

    In the running application these are overridden per model by Track B's
    ``alerts.services.resolve_thresholds()``. The engine keeps its own copy so
    it stays runnable — and testable — with no database.
    """
    return {
        "psi_moderate": 0.10,
        "psi_high": 0.25,
        "jsd_moderate": 0.10,
        "jsd_high": 0.20,
        "alpha": 0.05,
        "moderate_ratio_for_high": 0.30,
        "min_samples": float(C.MIN_SAMPLES_FOR_TEST),
    }


# ──────────────────────────────────────────────────────────────────────
# Proportion helpers
# ──────────────────────────────────────────────────────────────────────


def to_proportions(counts) -> np.ndarray:
    """Normalise counts to proportions summing to 1. All-zero input stays zero."""
    array = np.asarray(counts, dtype=float)
    total = array.sum()
    if total <= 0:
        return np.zeros_like(array)
    return array / total


def smooth(proportions: np.ndarray, epsilon: float = EPSILON) -> np.ndarray:
    """Add `epsilon` to every proportion and renormalise.

    Laplace-style smoothing. Without it, any bin that is empty in the baseline
    makes PSI's ``ln(actual / expected)`` term infinite — and empty bins are
    common, not exotic: a category the batch introduces for the first time
    produces one every single run.
    """
    shifted = np.asarray(proportions, dtype=float) + epsilon
    return shifted / shifted.sum()


# ──────────────────────────────────────────────────────────────────────
# The four measures
# ──────────────────────────────────────────────────────────────────────


def population_stability_index(
    baseline_proportions, current_proportions, epsilon: float = EPSILON
) -> float:
    """PSI = Σ (actual − expected) · ln(actual / expected).

    The standard credit-risk measure of population shift. Symmetric in practice,
    unbounded above, and banded < 0.10 / 0.10–0.25 / > 0.25 by long convention —
    which is worth citing in the report rather than presenting as our own choice.
    """
    expected = smooth(to_proportions(baseline_proportions), epsilon)
    actual = smooth(to_proportions(current_proportions), epsilon)

    if expected.size != actual.size:
        raise ValueError(
            f"PSI needs matching bin counts, got {expected.size} and {actual.size}"
        )
    if expected.size == 0:
        return 0.0

    return float(np.sum((actual - expected) * np.log(actual / expected)))


def jensen_shannon_divergence(
    baseline_proportions, current_proportions, epsilon: float = EPSILON
) -> float:
    """JSD in base 2, so the result is bounded to [0, 1].

    JSD(P‖Q) = ½·KL(P‖M) + ½·KL(Q‖M),  where M = (P + Q) / 2

    Base 2 matters: with natural logs the upper bound is ln(2) ≈ 0.693 and the
    PRD's 0.10 / 0.20 bands would mean something different from what they say.

    Unlike PSI this is bounded and symmetric, which makes it a useful
    cross-check — the two disagreeing is a signal worth seeing.
    """
    p = smooth(to_proportions(baseline_proportions), epsilon)
    q = smooth(to_proportions(current_proportions), epsilon)

    if p.size != q.size:
        raise ValueError(f"JSD needs matching bin counts, got {p.size} and {q.size}")
    if p.size == 0:
        return 0.0

    m = (p + q) / 2.0
    divergence = 0.5 * stats.entropy(p, m, base=2) + 0.5 * stats.entropy(q, m, base=2)

    # Clamp: floating-point error can produce -1e-17 or 1.0000000000000002.
    return float(min(max(divergence, 0.0), 1.0))


def _cap(values: np.ndarray, limit: int = MAX_TEST_SAMPLE) -> np.ndarray:
    """Randomly subsample to `limit` values using a fixed seed."""
    if values.size <= limit:
        return values
    rng = np.random.default_rng(SAMPLE_SEED)
    return rng.choice(values, size=limit, replace=False)


def ks_test(baseline_values, current_values) -> tuple[float, float]:
    """Two-sample Kolmogorov–Smirnov test for numeric features.

    Returns ``(D, p_value)``. D is the largest vertical gap between the two
    empirical CDFs, in [0, 1].

    Degenerate inputs return ``(0.0, 1.0)`` — "no evidence of difference" —
    rather than NaN, so a constant column can never poison a run.
    """
    baseline = np.asarray(baseline_values, dtype=float)
    current = np.asarray(current_values, dtype=float)
    baseline = baseline[~np.isnan(baseline)]
    current = current[~np.isnan(current)]

    if baseline.size == 0 or current.size == 0:
        return 0.0, 1.0

    # Both sides constant and equal: identical distributions, no difference.
    if baseline.size and current.size:
        if np.ptp(baseline) == 0 and np.ptp(current) == 0:
            return (0.0, 1.0) if baseline[0] == current[0] else (1.0, 0.0)

    statistic, p_value = stats.ks_2samp(_cap(baseline), _cap(current))
    return float(statistic), float(p_value)


def _merge_sparse_categories(
    baseline_counts: dict[str, float], current_counts: dict[str, float]
) -> tuple[list[float], list[float]]:
    """Align two count dicts on their shared category set, merging sparse ones.

    Chi-Square assumes every expected cell count is at least ~5. Rare categories
    violate that and inflate the statistic, so they are pooled into a single
    ``__OTHER__`` column — the standard remedy.
    """
    categories = sorted(set(baseline_counts) | set(current_counts))
    baseline = np.array([float(baseline_counts.get(c, 0.0)) for c in categories])
    current = np.array([float(current_counts.get(c, 0.0)) for c in categories])

    grand_total = baseline.sum() + current.sum()
    if grand_total <= 0:
        return [], []

    row_totals = np.array([baseline.sum(), current.sum()])
    column_totals = baseline + current
    # expected[i][j] = row_total[i] * column_total[j] / grand_total
    expected_min = np.outer(row_totals, column_totals).min(axis=0) / grand_total

    keep = expected_min >= MIN_EXPECTED_FREQUENCY
    if keep.all():
        return baseline.tolist(), current.tolist()

    kept_baseline = baseline[keep].tolist()
    kept_current = current[keep].tolist()

    pooled_baseline = float(baseline[~keep].sum())
    pooled_current = float(current[~keep].sum())
    if pooled_baseline + pooled_current > 0:
        kept_baseline.append(pooled_baseline)
        kept_current.append(pooled_current)

    return kept_baseline, kept_current


def chi_square_test(
    baseline_counts: dict[str, float], current_counts: dict[str, float]
) -> tuple[float, float]:
    """Chi-Square test of independence for categorical features.

    The contingency table is 2 × k: rows are (baseline, batch), columns are
    categories. A significant result means the category mix depends on which
    dataset a row came from — which is exactly what categorical drift is.

    Returns ``(0.0, 1.0)`` when the test is not defined (fewer than two usable
    categories, or an empty side) rather than raising.
    """
    baseline, current = _merge_sparse_categories(baseline_counts, current_counts)

    if len(baseline) < 2:
        return 0.0, 1.0
    if sum(baseline) == 0 or sum(current) == 0:
        return 0.0, 1.0

    table = np.array([baseline, current], dtype=float)

    # A column that is zero on both sides carries no information and makes the
    # test undefined.
    table = table[:, table.sum(axis=0) > 0]
    if table.shape[1] < 2:
        return 0.0, 1.0

    try:
        statistic, p_value, _, _ = stats.chi2_contingency(table)
    except ValueError:
        return 0.0, 1.0

    return float(statistic), float(p_value)


# ──────────────────────────────────────────────────────────────────────
# Classification
# ──────────────────────────────────────────────────────────────────────


def band(value: float, moderate: float, high: float) -> str:
    """Map a magnitude onto NONE / MODERATE / HIGH."""
    if value > high:
        return C.HIGH
    if value >= moderate:
        return C.MODERATE
    return C.NONE


def worst(*statuses: str) -> str:
    """The most severe of the given statuses."""
    return max(statuses, key=C.DRIFT_SEVERITY_ORDER.index)


def _downgrade(status: str) -> str:
    """One severity level below `status`."""
    index = C.DRIFT_SEVERITY_ORDER.index(status)
    return C.DRIFT_SEVERITY_ORDER[max(index - 1, 0)]


def classify_feature(
    psi: float,
    jsd: float,
    p_value: float,
    n_baseline: int,
    n_current: int,
    thresholds: dict[str, float] | None = None,
) -> str:
    """Combine magnitude and significance into one status. PRD §7.3.

    The order matters:

    1. Too little data on either side → INSUFFICIENT_DATA. Reporting NONE here
       would be a lie: we did not fail to find drift, we were unable to look.
    2. Magnitude (the worse of the PSI and JSD bands) proposes a status.
    3. Significance confirms it. If the shift is large but the test cannot rule
       out chance, the status is downgraded one level rather than dropped —
       that is the small-sample guard.
    """
    thresholds = thresholds or default_thresholds()
    minimum = int(thresholds.get("min_samples", C.MIN_SAMPLES_FOR_TEST))

    if n_baseline < minimum or n_current < minimum:
        return C.INSUFFICIENT_DATA

    magnitude = worst(
        band(psi, thresholds["psi_moderate"], thresholds["psi_high"]),
        band(jsd, thresholds["jsd_moderate"], thresholds["jsd_high"]),
    )

    if magnitude == C.NONE:
        return C.NONE

    return magnitude if p_value < thresholds["alpha"] else _downgrade(magnitude)


def rollup(
    results: list[dict[str, Any]], thresholds: dict[str, float] | None = None
) -> str:
    """Roll per-feature statuses up to one status for the run. PRD §7.4.

    HIGH if any single feature is HIGH, or if a large enough share of features
    are MODERATE — many features drifting together is a distribution shift even
    when no individual feature looks alarming.

    INSUFFICIENT_DATA and excluded features are left out of both the numerator
    and the denominator.
    """
    thresholds = thresholds or default_thresholds()

    evaluated = [r for r in results if r["status"] in (C.NONE, C.MODERATE, C.HIGH)]
    if not evaluated:
        return C.NONE

    high = sum(1 for r in evaluated if r["status"] == C.HIGH)
    moderate = sum(1 for r in evaluated if r["status"] == C.MODERATE)

    if (
        high >= 1
        or (moderate / len(evaluated)) >= thresholds["moderate_ratio_for_high"]
    ):
        return C.HIGH
    if moderate >= 1:
        return C.MODERATE
    return C.NONE


# ──────────────────────────────────────────────────────────────────────
# Per-feature analysis
# ──────────────────────────────────────────────────────────────────────


def _analyse_numeric(
    column: str,
    profile_entry: dict[str, Any],
    reference_values: np.ndarray,
    batch_series: pd.Series,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    edges = profile_entry.get("bin_edges") or []
    baseline_counts = profile_entry.get("bin_counts") or []
    batch_values = batch_series.to_numpy()

    current_counts = profiling.bin_counts(batch_values, edges) if edges else []

    if (
        baseline_counts
        and current_counts
        and len(baseline_counts) == len(current_counts)
    ):
        psi = population_stability_index(baseline_counts, current_counts)
        jsd = jensen_shannon_divergence(baseline_counts, current_counts)
    else:
        psi, jsd = 0.0, 0.0

    statistic, p_value = ks_test(reference_values, batch_values)

    n_baseline = int(profile_entry["summary"]["count"])
    n_current = int(batch_series.notna().sum())

    return {
        "feature_name": column,
        "feature_type": C.NUMERIC,
        "test_name": C.KS,
        "test_statistic": statistic,
        "p_value": p_value,
        "psi": psi,
        "jsd": jsd,
        "status": classify_feature(
            psi, jsd, p_value, n_baseline, n_current, thresholds
        ),
        "baseline_summary": profile_entry["summary"],
        "current_summary": profiling.summarise_numeric(batch_series),
        "unseen_categories": [],
    }


def _analyse_categorical(
    column: str,
    profile_entry: dict[str, Any],
    batch_series: pd.Series,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    baseline_counts = {str(k): float(v) for k, v in profile_entry["categories"].items()}
    current_summary = profiling.summarise_categorical(batch_series)
    current_counts = {
        str(k): float(v) for k, v in current_summary["categories"].items()
    }

    # Categories the batch introduced that the baseline never saw. These push PSI
    # up on their own (their baseline proportion smooths to epsilon) and are also
    # reported so the data-quality module can flag them.
    unseen = sorted(set(current_counts) - set(baseline_counts))

    categories = sorted(set(baseline_counts) | set(current_counts))
    baseline_vector = [baseline_counts.get(c, 0.0) for c in categories]
    current_vector = [current_counts.get(c, 0.0) for c in categories]

    psi = population_stability_index(baseline_vector, current_vector)
    jsd = jensen_shannon_divergence(baseline_vector, current_vector)
    statistic, p_value = chi_square_test(baseline_counts, current_counts)

    n_baseline = int(profile_entry["summary"]["count"])
    n_current = int(batch_series.notna().sum())

    return {
        "feature_name": column,
        "feature_type": C.CATEGORICAL,
        "test_name": C.CHI2,
        "test_statistic": statistic,
        "p_value": p_value,
        "psi": psi,
        "jsd": jsd,
        "status": classify_feature(
            psi, jsd, p_value, n_baseline, n_current, thresholds
        ),
        "baseline_summary": profile_entry["summary"],
        "current_summary": current_summary,
        "unseen_categories": unseen,
    }


def analyse_features(
    baseline_profile: dict[str, Any],
    reference_sample: pd.DataFrame,
    batch_df: pd.DataFrame,
    schema: dict[str, dict[str, Any]],
    thresholds: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Run the full drift analysis over every monitored feature.

    `reference_sample` supplies raw baseline values for the K-S test, which
    needs samples rather than bins. PSI, JSD and Chi-Square all work from the
    stored profile, so the baseline CSV is never re-read.

    Results come back sorted worst-drift-first, which is the order the run
    detail table displays by default (PRD FR-08.2).
    """
    thresholds = thresholds or default_thresholds()
    results: list[dict[str, Any]] = []

    for column, entry in baseline_profile.get("columns", {}).items():
        spec = schema.get(column)
        if spec is not None and not spec.get("is_feature", True):
            continue

        if column not in batch_df.columns:
            # Schema validation rejects batches missing a required column before
            # this point (BACKEND_FLOW.md §4 step 4). Reaching here means the
            # column was optional; record it honestly rather than scoring it.
            results.append(
                {
                    "feature_name": column,
                    "feature_type": entry["type"],
                    "test_name": C.KS if entry["type"] == C.NUMERIC else C.CHI2,
                    "test_statistic": None,
                    "p_value": None,
                    "psi": None,
                    "jsd": None,
                    "status": C.INSUFFICIENT_DATA,
                    "baseline_summary": entry["summary"],
                    "current_summary": None,
                    "unseen_categories": [],
                }
            )
            continue

        batch_series = batch_df[column]

        if entry["type"] == C.NUMERIC:
            reference_values = (
                reference_sample[column].to_numpy()
                if column in reference_sample.columns
                else np.array([])
            )
            results.append(
                _analyse_numeric(
                    column, entry, reference_values, batch_series, thresholds
                )
            )
        else:
            results.append(
                _analyse_categorical(column, entry, batch_series, thresholds)
            )

    severity = {C.HIGH: 0, C.MODERATE: 1, C.NONE: 2, C.INSUFFICIENT_DATA: 3}
    results.sort(key=lambda r: (severity[r["status"]], -(r["psi"] or 0.0)))
    return results
