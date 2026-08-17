"""Dashboard, model tabs and the chart JSON endpoints — PRD FR-07.

Every endpoint reads real monitoring runs. Two rules run through all of them:

* **Unlabelled runs render as gaps, never as zero** (FR-04.7). A batch with no
  ground truth has unknown accuracy; plotting it as 0 turns the performance
  chart into a cliff and makes a healthy model look broken.
* **Series are capped and down-sampled server-side** at 500 points, so a model
  with thousands of runs still renders (TRD §10).
"""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from accounts.models import LoginActivity, User
from alerts.models import Alert, RetrainRecommendation
from core.constants import (
    AlertSeverity,
    AlertStatus,
    DriftStatus,
    RetrainStatus,
    Role,
    RunStatus,
)
from core.mixins import visible_models
from monitoring.models import FeatureDriftResult, MonitoringRun

MAX_POINTS = 500

RANGES = {"24h": 1, "7d": 7, "30d": 30, "all": None}


def downsample(values, max_points=MAX_POINTS):
    """Evenly thin a series, always keeping the newest point.

    The most recent value is what a reader looks at first, so it must survive
    thinning even when the stride would otherwise skip it.
    """
    if len(values) <= max_points:
        return values
    step = len(values) / max_points
    thinned = [values[int(i * step)] for i in range(max_points - 1)]
    thinned.append(values[-1])
    return thinned


def _runs_for(request, ml_model):
    """Completed runs for a model within the requested range, oldest first."""
    window = RANGES.get(request.GET.get("range", "30d"), 30)
    # select_related on the 1:1 children: without it every chart endpoint issues
    # one extra query per run, so a model with 500 runs costs 500 queries.
    queryset = ml_model.runs.filter(status=RunStatus.COMPLETED).select_related(
        "performance", "quality"
    )
    if window is not None:
        queryset = queryset.filter(
            created_at__gte=timezone.now() - timedelta(days=window)
        )
    return list(queryset.order_by("created_at"))


def _model_or_404(request, slug):
    return get_object_or_404(visible_models(request.user), slug=slug)


def _labels(runs):
    return [run.created_at.strftime("%d %b %H:%M") for run in runs]


# ══════════════════════════════════════════════════════════════════
# S2 — the role-aware dashboard
# ══════════════════════════════════════════════════════════════════


@login_required
def dashboard_index(request):
    user = request.user
    models = list(visible_models(user).select_related("owner"))

    unresolved = Alert.objects.filter(
        ml_model__in=models, status__in=[AlertStatus.NEW, AlertStatus.ACKNOWLEDGED]
    ).select_related("ml_model")

    # Latest run per model, for the health cards.
    cards = []
    for ml_model in models:
        latest = (
            ml_model.runs.filter(status=RunStatus.COMPLETED)
            .order_by("-created_at")
            .first()
        )
        active_version = ml_model.versions.filter(status="ACTIVE").first()
        cards.append(
            {
                "model": ml_model,
                "run": latest,
                "version": active_version,
                "needs_attention": bool(
                    latest and latest.health_band in ("WARNING", "CRITICAL")
                ),
            }
        )

    # Worst health first, so anything wrong is at the top of the page.
    cards.sort(key=lambda c: (c["run"].health_score if c["run"] else 101))

    context = {
        "user_role": user.role,
        "cards": cards,
        "total_models": len(models),
        "active_alerts_count": unresolved.count(),
        "open_recommendations_count": RetrainRecommendation.objects.filter(
            ml_model__in=models, status=RetrainStatus.OPEN
        ).count(),
        "recommendations": RetrainRecommendation.objects.filter(
            ml_model__in=models, status=RetrainStatus.OPEN
        ).select_related("ml_model")[:5],
        "alerts": unresolved[:8],
        "recent_runs": MonitoringRun.objects.filter(ml_model__in=models)
        .select_related("ml_model")
        .order_by("-created_at")[:8],
        "attention": [c for c in cards if c["needs_attention"]],
    }

    if user.role == Role.ADMIN or user.is_superuser:
        context["total_users"] = User.objects.count()
        context["active_users_today"] = (
            LoginActivity.objects.filter(
                event="LOGIN_SUCCESS",
                occurred_at__gte=timezone.now() - timedelta(days=1),
            )
            .values("user")
            .distinct()
            .count()
        )
        context["recent_activities"] = LoginActivity.objects.select_related("user")[:8]

    context["nav"] = "dashboard"
    return render(request, "dashboard/index.html", context)


# ══════════════════════════════════════════════════════════════════
# Chart endpoints — FR-07
# ══════════════════════════════════════════════════════════════════


@login_required
def chart_performance_api(request, slug):
    """FR-07.1 — accuracy, precision, recall and F1 over time.

    Unlabelled runs contribute ``None``, which Chart.js renders as a gap because
    the line factory sets ``spanGaps: false``. Interpolating across them would
    invent measurements that were never taken.
    """
    ml_model = _model_or_404(request, slug)
    runs = _runs_for(request, ml_model)

    series = {"accuracy": [], "precision": [], "recall": [], "f1": []}
    labels = []

    for run in runs:
        snapshot = getattr(run, "performance", None)
        labels.append(run.created_at.strftime("%d %b %H:%M"))
        if snapshot is None or not snapshot.labels_available:
            for key in series:
                series[key].append(None)
            continue
        series["accuracy"].append(snapshot.accuracy)
        series["precision"].append(
            snapshot.precision_positive or snapshot.precision_macro
        )
        series["recall"].append(snapshot.recall_positive or snapshot.recall_macro)
        series["f1"].append(snapshot.f1_positive or snapshot.f1_macro)

    labelled = sum(1 for v in series["accuracy"] if v is not None)
    return JsonResponse(
        {
            "model": ml_model.name,
            "labels": downsample(labels),
            "series": {k: downsample(v) for k, v in series.items()},
            "labelled_runs": labelled,
            "unlabelled_runs": len(runs) - labelled,
        }
    )


@login_required
def chart_drift_api(request, slug):
    """FR-07.2 — feature counts by drift status, plus the worst PSI seen.

    Two separate charts rather than one with two y-axes. Counts and PSI are
    different scales, and a dual-axis chart is the single most misread form
    there is (UIUX §5.4).
    """
    ml_model = _model_or_404(request, slug)
    runs = _runs_for(request, ml_model)

    # One aggregate for every run, rather than a query per run.
    from django.db.models import Max

    worst_by_run = dict(
        FeatureDriftResult.objects.filter(run__in=runs, psi__isnull=False)
        .values_list("run_id")
        .annotate(worst=Max("psi"))
    )
    max_psi = [
        round(worst_by_run[r.pk], 4) if r.pk in worst_by_run else None for r in runs
    ]

    return JsonResponse(
        {
            "model": ml_model.name,
            "labels": downsample(_labels(runs)),
            "counts": {
                "high": downsample([r.features_high for r in runs]),
                "moderate": downsample([r.features_moderate for r in runs]),
                "none": downsample([r.features_clean for r in runs]),
            },
            "max_psi": downsample(max_psi),
        }
    )


@login_required
def chart_health_trend_api(request, slug):
    """FR-07.6 — the health score over time, with its band boundaries."""
    ml_model = _model_or_404(request, slug)
    runs = _runs_for(request, ml_model)
    thresholds = runs[-1].thresholds_snapshot if runs else {}

    return JsonResponse(
        {
            "model": ml_model.name,
            "labels": downsample(_labels(runs)),
            "scores": downsample([r.health_score for r in runs]),
            "bands": downsample([r.health_band for r in runs]),
            "warning_at": thresholds.get("health_warning_threshold", 80),
            "critical_at": thresholds.get("health_critical_threshold", 60),
        }
    )


@login_required
def chart_prediction_trend_api(request, slug):
    """FR-07.4 — the predicted class mix over time.

    Available for every run, labelled or not: it is the only behavioural signal
    a model gives you without ground truth.
    """
    ml_model = _model_or_404(request, slug)
    runs = _runs_for(request, ml_model)

    classes = set()
    per_run = []
    for run in runs:
        snapshot = getattr(run, "performance", None)
        proportions = (
            (snapshot.prediction_distribution or {}).get("proportions", {})
            if snapshot
            else {}
        )
        per_run.append(proportions)
        classes.update(proportions)

    ordered = sorted(classes)
    return JsonResponse(
        {
            "model": ml_model.name,
            "labels": downsample(_labels(runs)),
            "series": {
                name: downsample([round(100 * p.get(name, 0.0), 2) for p in per_run])
                for name in ordered
            },
        }
    )


@login_required
def chart_alerts_trend_api(request, slug):
    """FR-07.5 — alerts raised per day, split by severity."""
    ml_model = _model_or_404(request, slug)
    window = RANGES.get(request.GET.get("range", "30d"), 30) or 90
    since = timezone.now() - timedelta(days=window)

    alerts = Alert.objects.filter(ml_model=ml_model, first_seen_at__gte=since)

    # Bucket on the ISO date so the keys sort chronologically. Sorting the
    # display strings instead would order "01 Feb" before "02 Jan".
    buckets: dict[str, dict[str, int]] = {}
    for alert in alerts:
        day = alert.first_seen_at.date().isoformat()
        buckets.setdefault(day, {"INFO": 0, "WARNING": 0, "CRITICAL": 0})
        buckets[day][alert.severity] = buckets[day].get(alert.severity, 0) + 1

    days = sorted(buckets)
    return JsonResponse(
        {
            "model": ml_model.name,
            "labels": [
                timezone.datetime.fromisoformat(d).strftime("%d %b") for d in days
            ],
            "series": {
                "info": [buckets[d].get(AlertSeverity.INFO, 0) for d in days],
                "warning": [buckets[d].get(AlertSeverity.WARNING, 0) for d in days],
                "critical": [buckets[d].get(AlertSeverity.CRITICAL, 0) for d in days],
            },
        }
    )


@login_required
def chart_distribution_api(request, slug):
    """FR-07.3 — baseline vs latest batch for one feature.

    Delegates to the monitoring app so there is exactly one implementation of
    the histogram comparison rather than two that can disagree.
    """
    from monitoring.views import feature_distribution_api

    ml_model = _model_or_404(request, slug)
    feature = request.GET.get("feature")
    latest = (
        ml_model.runs.filter(status=RunStatus.COMPLETED).order_by("-created_at").first()
    )

    if latest is None or not feature:
        return JsonResponse(
            {"type": "empty", "labels": [], "baseline": [], "current": []}
        )
    return feature_distribution_api(request, latest.pk, feature)


@login_required
def chart_feature_distribution_api(request, slug, feature_name):
    from monitoring.views import feature_distribution_api

    ml_model = _model_or_404(request, slug)
    latest = (
        ml_model.runs.filter(status=RunStatus.COMPLETED).order_by("-created_at").first()
    )
    if latest is None:
        return JsonResponse(
            {"type": "empty", "labels": [], "baseline": [], "current": []}
        )
    return feature_distribution_api(request, latest.pk, feature_name)


# ══════════════════════════════════════════════════════════════════
# S9 / S10 / S11 — model detail tabs
# ══════════════════════════════════════════════════════════════════


def _tab_context(request, slug, tab):
    ml_model = _model_or_404(request, slug)
    latest = (
        ml_model.runs.filter(status=RunStatus.COMPLETED)
        .select_related("quality", "performance")
        .order_by("-created_at")
        .first()
    )
    return ml_model, latest, {"ml_model": ml_model, "run": latest, "tab": tab}


@login_required
def model_drift_tab_view(request, slug):
    ml_model, latest, context = _tab_context(request, slug, "drift")
    context["results"] = (
        sorted(
            latest.feature_results.all(),
            key=lambda r: (
                {DriftStatus.HIGH: 0, DriftStatus.MODERATE: 1, DriftStatus.NONE: 2}.get(
                    r.status, 3
                ),
                -(r.psi or 0),
            ),
        )
        if latest
        else []
    )
    return render(request, "dashboard/model_drift_tab.html", context)


@login_required
def model_performance_tab_view(request, slug):
    ml_model, latest, context = _tab_context(request, slug, "performance")
    context["performance"] = getattr(latest, "performance", None) if latest else None
    return render(request, "dashboard/model_performance_tab.html", context)


@login_required
def model_quality_tab_view(request, slug):
    ml_model, latest, context = _tab_context(request, slug, "quality")
    context["quality"] = getattr(latest, "quality", None) if latest else None
    return render(request, "dashboard/model_quality_tab.html", context)
