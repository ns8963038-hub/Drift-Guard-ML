"""Run detail (S13) and feature drift detail (S14).

S13 is the centre of gravity of the whole application — every path that produces
or references a monitoring result funnels into it. S14 is where the plain-English
explanations land, which is the feature the client starred as the differentiator.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from core.constants import DriftStatus
from core.mixins import visible_models
from monitoring.models import FeatureDriftResult, MonitoringRun

# Worst first — the order the feature table defaults to (FR-08.2).
STATUS_ORDER = {
    DriftStatus.HIGH: 0,
    DriftStatus.MODERATE: 1,
    DriftStatus.NONE: 2,
    DriftStatus.INSUFFICIENT_DATA: 3,
}

SORTABLE = {
    "feature": lambda r: r.feature_name.lower(),
    "type": lambda r: r.feature_type,
    "statistic": lambda r: -(r.test_statistic or 0),
    "pvalue": lambda r: r.p_value if r.p_value is not None else 1.0,
    "psi": lambda r: -(r.psi or 0),
    "jsd": lambda r: -(r.jsd or 0),
    "status": lambda r: (STATUS_ORDER.get(r.status, 9), -(r.psi or 0)),
}


def _visible_run(user, run_id):
    """A run the caller is allowed to see, or 404.

    Scoped through visible_models so an ungranted model's runs are unreachable
    by id, and indistinguishable from a run that does not exist (FR-01.7).
    """
    return get_object_or_404(
        MonitoringRun.objects.select_related(
            "ml_model", "model_version", "data_batch", "quality", "performance"
        ),
        pk=run_id,
        ml_model__in=visible_models(user),
    )


@login_required
def run_detail_view(request, run_id):
    """S13 — the full result of one monitoring run."""
    run = _visible_run(request.user, run_id)

    sort = request.GET.get("sort", "status")
    results = list(run.feature_results.all())
    results.sort(key=SORTABLE.get(sort, SORTABLE["status"]))

    components = run.health_components.get("components", {})
    weights = run.health_components.get("weights", {})

    return render(
        request,
        "monitoring/run_detail.html",
        {
            "run": run,
            "ml_model": run.ml_model,
            "results": results,
            "sort": sort,
            "quality": getattr(run, "quality", None),
            "performance": getattr(run, "performance", None),
            "health_breakdown": [
                {
                    "name": name.replace("_", " ").title(),
                    "score": components.get(name),
                    "weight": weights.get(name, 0),
                }
                # Fixed order so the breakdown reads the same on every run.
                for name in ("performance", "drift", "quality", "stability")
            ],
            "weighting": run.health_components.get("weighting", ""),
            "alerts": run.alerts.all()[:10],
        },
    )


@login_required
def feature_detail_view(request, run_id, feature_name):
    """S14 — one feature's distributions, statistics and explanation."""
    run = _visible_run(request.user, run_id)
    result = get_object_or_404(FeatureDriftResult, run=run, feature_name=feature_name)

    # This feature's status across recent runs, oldest first, for the sparkline.
    history = list(
        FeatureDriftResult.objects.filter(
            run__ml_model=run.ml_model, feature_name=feature_name
        )
        .select_related("run")
        .order_by("-run__created_at")[:30]
    )
    history.reverse()

    return render(
        request,
        "monitoring/feature_detail.html",
        {
            "run": run,
            "ml_model": run.ml_model,
            "result": result,
            "history": history,
            "summary_rows": _summary_rows(result),
        },
    )


def _summary_rows(result):
    """Baseline-vs-current statistics, formatted for a two-column table."""
    baseline = result.baseline_summary or {}
    current = result.current_summary or {}

    if result.feature_type == "NUMERIC":
        keys = [
            ("mean", "Mean"),
            ("std", "Std deviation"),
            ("min", "Minimum"),
            ("q1", "25th percentile"),
            ("median", "Median"),
            ("q3", "75th percentile"),
            ("max", "Maximum"),
            ("missing_pct", "Missing %"),
        ]
    else:
        keys = [
            ("count", "Rows"),
            ("n_unique", "Distinct values"),
            ("missing_pct", "Missing %"),
        ]

    return [
        {"label": label, "baseline": baseline.get(key), "current": current.get(key)}
        for key, label in keys
        if key in baseline or key in current
    ]


@login_required
def run_status_api(request, run_id):
    """Polled by the progress panel after a batch is submitted (APP_FLOW §6.2)."""
    run = _visible_run(request.user, run_id)
    return JsonResponse(
        {
            "status": run.status,
            "drift_status": run.overall_drift_status,
            "health_score": run.health_score,
            "health_band": run.health_band,
            "error": run.error_message,
            "detail_url": f"/runs/{run.pk}/",
        }
    )


@login_required
def feature_distribution_api(request, run_id, feature_name):
    """Baseline vs current distribution for the S14 chart."""
    run = _visible_run(request.user, run_id)
    result = get_object_or_404(FeatureDriftResult, run=run, feature_name=feature_name)

    baseline = result.baseline_summary or {}
    current = result.current_summary or {}

    if result.feature_type == "CATEGORICAL":
        categories = sorted(
            set(baseline.get("proportions", {})) | set(current.get("proportions", {}))
        )
        return JsonResponse(
            {
                "type": "categorical",
                "labels": categories,
                "baseline": [
                    round(100 * baseline.get("proportions", {}).get(c, 0.0), 2)
                    for c in categories
                ],
                "current": [
                    round(100 * current.get("proportions", {}).get(c, 0.0), 2)
                    for c in categories
                ],
                "unit": "%",
            }
        )

    # Numeric: the profile's bin edges live on the baseline dataset, so the
    # histogram is rebuilt from the stored per-run summaries instead.
    profile = run.model_version.baseline.profile if run.model_version else {}
    entry = profile.get("columns", {}).get(feature_name, {})
    edges = entry.get("bin_edges") or []
    labels = [
        f"{edges[i]:,.1f}–{edges[i + 1]:,.1f}" for i in range(max(len(edges) - 1, 0))
    ]

    return JsonResponse(
        {
            "type": "numeric",
            "labels": labels,
            "baseline": entry.get("bin_counts") or [],
            "current": result.current_summary.get("bin_counts") or [],
            "unit": "rows",
        }
    )
