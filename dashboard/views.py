from datetime import timedelta
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from alerts.models import Alert, RetrainRecommendation
from accounts.models import User, LoginActivity
from core.constants import Role, AlertStatus, RetrainStatus
from core.mixins import visible_models


def downsample(data_list, max_points=500):
    if len(data_list) <= max_points:
        return data_list
    step = len(data_list) / max_points
    return [data_list[int(i * step)] for i in range(max_points)]


@login_required
def dashboard_index(request):
    user = request.user
    models = visible_models(user)

    total_models = models.count()
    unresolved_alerts = Alert.objects.filter(
        ml_model__in=models, status__in=[AlertStatus.NEW, AlertStatus.ACKNOWLEDGED]
    )
    active_alerts_count = unresolved_alerts.count()
    open_recommendations_count = RetrainRecommendation.objects.filter(
        ml_model__in=models, status=RetrainStatus.OPEN
    ).count()

    context = {
        "user_role": user.role,
        "total_models": total_models,
        "active_alerts_count": active_alerts_count,
        "open_recommendations_count": open_recommendations_count,
        "models": models[:5],
        "alerts": unresolved_alerts[:5],
    }

    if user.role == Role.ADMIN or user.is_superuser:
        context["total_users"] = User.objects.count()
        context["recent_activities"] = LoginActivity.objects.select_related(
            "user"
        ).all()[:5]

    return render(request, "dashboard/index.html", context)


@login_required
def chart_performance_api(request, slug):
    # STUB: returns generated placeholder points, not real data.
    # Repoint at MonitoringRun once Track A's models land (contract C3).
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    days = int(request.GET.get("days", 30))

    timestamps = []
    accuracy = []
    precision = []
    recall = []
    f1 = []

    now = timezone.now()
    for i in range(min(days * 4, 100)):
        ts = now - timedelta(hours=i * 6)
        timestamps.append(ts.strftime("%Y-%m-%d %H:%M"))
        accuracy.append(round(0.82 + (i % 5) * 0.01 - (i % 3) * 0.005, 4))
        precision.append(round(0.78 + (i % 4) * 0.01, 4))
        recall.append(round(0.75 + (i % 6) * 0.008, 4))
        f1.append(round(0.76 + (i % 5) * 0.009, 4))

    timestamps.reverse()
    accuracy.reverse()
    precision.reverse()
    recall.reverse()
    f1.reverse()

    data = {
        "model": ml_model.name,
        "timestamps": downsample(timestamps),
        "series": {
            "accuracy": downsample(accuracy),
            "precision": downsample(precision),
            "recall": downsample(recall),
            "f1": downsample(f1),
        },
    }
    return JsonResponse(data)


@login_required
def chart_drift_api(request, slug):
    # STUB: returns generated placeholder points, not real data.
    # Repoint at MonitoringRun once Track A's models land (contract C3).
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    days = int(request.GET.get("days", 30))

    timestamps = []
    ks_values = []
    chi2_values = []
    psi_values = []

    now = timezone.now()
    for i in range(min(days * 4, 100)):
        ts = now - timedelta(hours=i * 6)
        timestamps.append(ts.strftime("%Y-%m-%d %H:%M"))
        ks_values.append(round(0.02 + (i % 7) * 0.008, 4))
        chi2_values.append(round(0.01 + (i % 5) * 0.01, 4))
        psi_values.append(round(0.05 + (i % 9) * 0.015, 4))

    timestamps.reverse()
    ks_values.reverse()
    chi2_values.reverse()
    psi_values.reverse()

    data = {
        "model": ml_model.name,
        "timestamps": downsample(timestamps),
        "series": {
            "ks": downsample(ks_values),
            "chi2": downsample(chi2_values),
            "psi": downsample(psi_values),
        },
    }
    return JsonResponse(data)


@login_required
def chart_distribution_api(request, slug):
    # STUB: returns generated placeholder points, not real data.
    # Repoint at MonitoringRun once Track A's models land (contract C3).
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    data = {
        "model": ml_model.name,
        "categories": ["No", "Yes"],
        "baseline": [0.73, 0.27],
        "production": [0.65, 0.35],
    }
    return JsonResponse(data)


@login_required
def chart_prediction_trend_api(request, slug):
    # STUB: returns generated placeholder points, not real data.
    # Repoint at MonitoringRun once Track A's models land (contract C3).
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    timestamps = []
    positive_rate = []
    negative_rate = []

    now = timezone.now()
    for i in range(30):
        ts = now - timedelta(days=i)
        timestamps.append(ts.strftime("%Y-%m-%d"))
        pos = round(0.25 + (i % 4) * 0.02, 2)
        positive_rate.append(pos)
        negative_rate.append(round(1.0 - pos, 2))

    timestamps.reverse()
    positive_rate.reverse()
    negative_rate.reverse()

    data = {
        "model": ml_model.name,
        "timestamps": timestamps,
        "positive": positive_rate,
        "negative": negative_rate,
    }
    return JsonResponse(data)


@login_required
def chart_alerts_trend_api(request, slug):
    # STUB: returns generated placeholder points, not real data.
    # Repoint at MonitoringRun once Track A's models land (contract C3).
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    timestamps = []
    critical_counts = []
    warning_counts = []

    now = timezone.now()
    for i in range(14):
        ts = now - timedelta(days=i)
        timestamps.append(ts.strftime("%Y-%m-%d"))
        critical_counts.append(i % 3)
        warning_counts.append(i % 4)

    timestamps.reverse()
    critical_counts.reverse()
    warning_counts.reverse()

    data = {
        "model": ml_model.name,
        "timestamps": timestamps,
        "critical": critical_counts,
        "warning": warning_counts,
    }
    return JsonResponse(data)


@login_required
def chart_health_trend_api(request, slug):
    # STUB: returns generated placeholder points, not real data.
    # Repoint at MonitoringRun once Track A's models land (contract C3).
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    timestamps = []
    health_scores = []

    now = timezone.now()
    for i in range(30):
        ts = now - timedelta(days=i)
        timestamps.append(ts.strftime("%Y-%m-%d"))
        health_scores.append(max(40, 95 - (i % 10) * 3))

    timestamps.reverse()
    health_scores.reverse()

    data = {
        "model": ml_model.name,
        "timestamps": timestamps,
        "scores": health_scores,
    }
    return JsonResponse(data)


@login_required
def chart_feature_distribution_api(request, slug, feature_name):
    # STUB: returns generated placeholder points, not real data.
    # Repoint at MonitoringRun once Track A's models land (contract C3).
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    data = {
        "model": ml_model.name,
        "feature": feature_name,
        "bins": ["0-10", "10-20", "20-30", "30-40", "40-50"],
        "baseline_counts": [120, 240, 310, 180, 90],
        "production_counts": [90, 180, 350, 240, 140],
    }
    return JsonResponse(data)


@login_required
def model_drift_tab_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    return render(
        request,
        "dashboard/model_drift_tab.html",
        {"ml_model": ml_model, "tab": "drift"},
    )


@login_required
def model_performance_tab_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    return render(
        request,
        "dashboard/model_performance_tab.html",
        {"ml_model": ml_model, "tab": "performance"},
    )


@login_required
def model_quality_tab_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    return render(
        request,
        "dashboard/model_quality_tab.html",
        {"ml_model": ml_model, "tab": "quality"},
    )
