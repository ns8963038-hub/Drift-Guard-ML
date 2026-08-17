"""Explainable drift detection — PRD FR-14.

Turns four numbers into a sentence a non-statistician can act on. "PSI 0.34" is
a fact; "the average monthly charge rose 38% and the spread widened" is
something a person can do something about.

**Template-driven and deterministic.** No LLM, no external service, no network
call (FR-14.2). The same inputs always produce the same sentence, which means
explanations can be stored with the run and re-read years later, and nothing in
the demo depends on an internet connection.

Every explanation states three things:
  1. what moved, in the feature's real units
  2. which threshold was crossed and by how much
  3. whether the statistical test confirmed it

Pure Python. Imports no Django (BACKEND_FLOW.md §1).
"""

from __future__ import annotations

from typing import Any

from . import constants as C

STATUS_PHRASE = {
    C.HIGH: "High drift",
    C.MODERATE: "Moderate drift",
    C.NONE: "No drift",
    C.INSUFFICIENT_DATA: "Not enough data",
}


def _number(value: float | None, places: int = 2) -> str:
    """Format a value for prose, thousands-separated."""
    if value is None:
        return "n/a"
    return f"{value:,.{places}f}"


def _percent(value: float | None, places: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{places}f}%"


def _p_value(p: float | None) -> str:
    if p is None:
        return "n/a"
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}"


def _driving_measure(
    psi: float | None, jsd: float | None, thresholds: dict[str, float]
) -> tuple[str, float, float] | None:
    """Which measure crossed its threshold, and by how much (FR-14.5).

    PSI is preferred when both crossed, because it is the measure practitioners
    recognise and the one the report cites a convention for.
    """
    candidates = []
    if psi is not None:
        if psi > thresholds["psi_high"]:
            candidates.append(("PSI", psi, thresholds["psi_high"], "high", 0))
        elif psi >= thresholds["psi_moderate"]:
            candidates.append(("PSI", psi, thresholds["psi_moderate"], "moderate", 1))
    if jsd is not None:
        if jsd > thresholds["jsd_high"]:
            candidates.append(("JSD", jsd, thresholds["jsd_high"], "high", 0))
        elif jsd >= thresholds["jsd_moderate"]:
            candidates.append(("JSD", jsd, thresholds["jsd_moderate"], "moderate", 1))

    if not candidates:
        return None

    # Worst band first; PSI wins ties (it sorts before JSD on the last key).
    candidates.sort(key=lambda c: (c[4], 0 if c[0] == "PSI" else 1))
    name, value, threshold, band_name, _ = candidates[0]
    return (
        f"{name} is {value:.3f}, above the {band_name}-drift threshold of {threshold:.2f}",
        value,
        threshold,
    )


def _significance_clause(p_value: float | None, status: str, test_name: str) -> str:
    label = "K-S test" if test_name == C.KS else "Chi-Square test"
    if p_value is None:
        return ""
    if p_value < 0.05:
        return f" The {label} returns {_p_value(p_value)}, confirming the two distributions differ."
    return (
        f" The {label} returns {_p_value(p_value)}, so the difference is not "
        f"statistically confirmed at this sample size — the status has been "
        f"reduced by one level as a precaution."
    )


def explain_numeric(
    feature: str,
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
    scores: dict[str, Any],
    thresholds: dict[str, float],
) -> str:
    """Plain-English explanation for a numeric feature (FR-14.3)."""
    status = scores.get("status", C.NONE)

    if status == C.INSUFFICIENT_DATA:
        return (
            f"Not enough data to assess `{feature}`. At least "
            f"{int(thresholds.get('min_samples', 30))} non-empty values are needed on both "
            f"sides; this run had {current_summary.get('count', 0):,} in the batch."
        )

    baseline_mean = baseline_summary.get("mean")
    current_mean = current_summary.get("mean")
    baseline_std = baseline_summary.get("std")
    current_std = current_summary.get("std")

    if status == C.NONE:
        return (
            f"No drift in `{feature}`. The average is {_number(current_mean)} "
            f"against a baseline of {_number(baseline_mean)}, within normal variation."
        )

    parts = [f"{STATUS_PHRASE[status]} detected in `{feature}`."]

    # ── what moved: the mean ──────────────────────────────────────────
    if baseline_mean is not None and current_mean is not None:
        direction = "rose" if current_mean > baseline_mean else "fell"
        sentence = (
            f"The average {direction} from {_number(baseline_mean)} in the baseline "
            f"to {_number(current_mean)} in this batch"
        )
        if baseline_mean != 0:
            change = 100.0 * (current_mean - baseline_mean) / abs(baseline_mean)
            sentence += f" ({change:+.1f}%)"
        parts.append(sentence)

    # ── what moved: the spread ────────────────────────────────────────
    if (
        baseline_std is not None
        and current_std is not None
        and baseline_std != current_std
    ):
        spread = "widened" if current_std > baseline_std else "narrowed"
        parts[
            -1
        ] += f", and the spread {spread} (std {_number(baseline_std)} → {_number(current_std)})."
    elif len(parts) > 1:
        parts[-1] += "."

    # ── which threshold was crossed ───────────────────────────────────
    driver = _driving_measure(scores.get("psi"), scores.get("jsd"), thresholds)
    if driver:
        parts.append(driver[0] + ".")

    # ── did the test confirm it ───────────────────────────────────────
    clause = _significance_clause(
        scores.get("p_value"), status, scores.get("test_name", C.KS)
    )

    # ── did missing values jump ───────────────────────────────────────
    baseline_missing = baseline_summary.get("missing_pct") or 0.0
    current_missing = current_summary.get("missing_pct") or 0.0
    missing_note = ""
    if current_missing - baseline_missing > 1.0:
        missing_note = (
            f" Missing values also rose from {_percent(baseline_missing)} to "
            f"{_percent(current_missing)}."
        )

    return " ".join(parts) + clause + missing_note


def explain_categorical(
    feature: str,
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
    scores: dict[str, Any],
    thresholds: dict[str, float],
    unseen_categories: list[str] | None = None,
) -> str:
    """Plain-English explanation for a categorical feature (FR-14.4).

    Names the two categories that gained the most share and the two that lost
    the most, in percentage points — the form a person can actually read off a
    bar chart.
    """
    status = scores.get("status", C.NONE)
    unseen = unseen_categories or []

    if status == C.INSUFFICIENT_DATA:
        return (
            f"Not enough data to assess `{feature}`. At least "
            f"{int(thresholds.get('min_samples', 30))} non-empty values are needed on both "
            f"sides; this run had {current_summary.get('count', 0):,} in the batch."
        )

    baseline_proportions = baseline_summary.get("proportions") or {}
    current_proportions = current_summary.get("proportions") or {}

    if status == C.NONE:
        return (
            f"No drift in `{feature}`. Category proportions are close to the "
            f"baseline across all {len(baseline_proportions) or 0} categories."
        )

    # Percentage-point change per category.
    categories = set(baseline_proportions) | set(current_proportions)
    deltas = sorted(
        (
            (
                category,
                100.0 * baseline_proportions.get(category, 0.0),
                100.0 * current_proportions.get(category, 0.0),
            )
            for category in categories
        ),
        key=lambda item: item[2] - item[1],
        reverse=True,
    )

    parts = [f"{STATUS_PHRASE[status]} detected in `{feature}`."]

    risers = [d for d in deltas if d[2] - d[1] > 0.5][:2]
    fallers = [d for d in reversed(deltas) if d[1] - d[2] > 0.5][:2]

    clauses = []
    for category, before, after in risers:
        clauses.append(
            f"the share of *{category}* rose from {_percent(before)} to "
            f"{_percent(after)} ({after - before:+.1f} points)"
        )
    for category, before, after in fallers:
        clauses.append(
            f"*{category}* fell from {_percent(before)} to {_percent(after)} "
            f"({after - before:+.1f} points)"
        )

    if clauses:
        joined = clauses[0]
        if len(clauses) > 1:
            joined += " while " + ", ".join(clauses[1:])
        # Uppercase only the first character. str.capitalize() would lowercase
        # everything after it and mangle category names such as "Month-to-month",
        # "USA" or "iPhone" — which appear verbatim in this sentence.
        parts.append(joined[:1].upper() + joined[1:] + ".")

    if unseen:
        listed = ", ".join(f"*{value}*" for value in unseen[:3])
        suffix = f" and {len(unseen) - 3} more" if len(unseen) > 3 else ""
        parts.append(
            f"The batch also contains {listed}{suffix}, which never appeared in the "
            f"baseline data."
        )

    driver = _driving_measure(scores.get("psi"), scores.get("jsd"), thresholds)
    if driver:
        parts.append(driver[0] + ".")

    clause = _significance_clause(
        scores.get("p_value"), status, scores.get("test_name", C.CHI2)
    )
    return " ".join(parts) + clause


def explain(result: dict[str, Any], thresholds: dict[str, float]) -> str:
    """Dispatch to the numeric or categorical explainer for one drift result."""
    if result.get("current_summary") is None:
        return (
            f"`{result['feature_name']}` was not present in this batch, so it could "
            f"not be assessed."
        )

    if result["feature_type"] == C.NUMERIC:
        return explain_numeric(
            result["feature_name"],
            result["baseline_summary"],
            result["current_summary"],
            result,
            thresholds,
        )

    return explain_categorical(
        result["feature_name"],
        result["baseline_summary"],
        result["current_summary"],
        result,
        thresholds,
        result.get("unseen_categories"),
    )


def explain_all(
    results: list[dict[str, Any]], thresholds: dict[str, float]
) -> list[dict[str, Any]]:
    """Attach an ``explanation`` to every drift result, in place-safe fashion."""
    return [
        {**result, "explanation": explain(result, thresholds)} for result in results
    ]
