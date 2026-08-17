from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from core.mixins import role_required, model_permission_required
from core.constants import Role, Permission
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from alerts.models import ThresholdProfile, Alert, RetrainRecommendation
from core.constants import AlertSeverity, AlertStatus, RetrainStatus
from core.mixins import visible_models


@login_required
def alert_list_view(request):
    user_models = visible_models(request.user)
    alerts = Alert.objects.filter(ml_model__in=user_models).select_related("ml_model")

    status_filter = request.GET.get("status")
    severity_filter = request.GET.get("severity")

    if status_filter:
        alerts = alerts.filter(status=status_filter)
    if severity_filter:
        alerts = alerts.filter(severity=severity_filter)

    return render(
        request,
        "alerts/alert_list.html",
        {
            "alerts": alerts,
            "status_choices": AlertStatus.choices,
            "severity_choices": AlertSeverity.choices,
            "current_status": status_filter,
            "current_severity": severity_filter,
        },
    )


@login_required
def alert_detail_view(request, alert_id):
    user_models = visible_models(request.user)
    alert = get_object_or_404(Alert, pk=alert_id, ml_model__in=user_models)
    return render(request, "alerts/alert_detail.html", {"alert": alert})


@login_required
def alert_acknowledge_view(request, alert_id):
    user_models = visible_models(request.user)
    alert = get_object_or_404(Alert, pk=alert_id, ml_model__in=user_models)
    if request.method == "POST":
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = request.user
        alert.acknowledged_at = timezone.now()
        alert.save(update_fields=["status", "acknowledged_by", "acknowledged_at"])
        messages.success(request, f"Alert #{alert.id} acknowledged.")
    return redirect("alerts:detail", alert_id=alert.id)


@login_required
def alert_resolve_view(request, alert_id):
    user_models = visible_models(request.user)
    alert = get_object_or_404(Alert, pk=alert_id, ml_model__in=user_models)
    if request.method == "POST":
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["status", "resolved_at"])
        messages.success(request, f"Alert #{alert.id} resolved.")
    return redirect("alerts:detail", alert_id=alert.id)


@login_required
@role_required(Role.DATA_SCIENTIST)
@model_permission_required(Permission.MANAGE)
def threshold_settings_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    # Ownership implies MANAGE. PRD §5.1: the creator of a model automatically
    # receives a MANAGE grant, so the owner and a MANAGE grant-holder are the
    # same authority. Checking only for the grant row made this view disagree
    # with visible_models() and with model_permission_required(), and would lock
    # a Data Scientist out of their own model if the grant row were ever missing.
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        if ml_model.owner_id != request.user.id:
            grant = ml_model.access_grants.filter(user=request.user).first()
            if not grant or grant.permission != Permission.MANAGE:
                raise PermissionDenied(
                    "Threshold configuration requires MANAGE permission."
                )

    profile, _ = ThresholdProfile.objects.get_or_create(ml_model=ml_model)

    if request.method == "POST":
        profile.ks_p_value_threshold = float(
            request.POST.get("ks_p_value_threshold", 0.05)
        )
        profile.chi2_p_value_threshold = float(
            request.POST.get("chi2_p_value_threshold", 0.05)
        )
        profile.psi_threshold = float(request.POST.get("psi_threshold", 0.2))
        profile.js_threshold = float(request.POST.get("js_threshold", 0.1))
        profile.missing_value_rate_threshold = float(
            request.POST.get("missing_value_rate_threshold", 0.05)
        )
        profile.duplicate_row_rate_threshold = float(
            request.POST.get("duplicate_row_rate_threshold", 0.01)
        )
        profile.outlier_rate_threshold = float(
            request.POST.get("outlier_rate_threshold", 0.05)
        )
        profile.accuracy_drop_threshold = float(
            request.POST.get("accuracy_drop_threshold", 0.05)
        )
        profile.health_warning_threshold = int(
            request.POST.get("health_warning_threshold", 70)
        )
        profile.health_critical_threshold = int(
            request.POST.get("health_critical_threshold", 50)
        )
        profile.save()
        messages.success(request, f"Threshold profile updated for {ml_model.name}.")
        return redirect("alerts:thresholds", slug=ml_model.slug)

    return render(
        request,
        "alerts/threshold_settings.html",
        {"ml_model": ml_model, "profile": profile, "tab": "thresholds"},
    )


@login_required
def retrain_recommendations_view(request):
    user_models = visible_models(request.user)
    recommendations = RetrainRecommendation.objects.filter(
        ml_model__in=user_models
    ).select_related("ml_model", "version")

    if request.method == "POST":
        rec_id = request.POST.get("recommendation_id")
        action = request.POST.get("action")
        rec = get_object_or_404(
            RetrainRecommendation, pk=rec_id, ml_model__in=user_models
        )
        if action == "dismiss":
            rec.status = RetrainStatus.DISMISSED
            rec.save(update_fields=["status"])
            messages.success(request, f"Recommendation #{rec.id} dismissed.")
        elif action == "acknowledge":
            rec.status = RetrainStatus.ACKNOWLEDGED
            rec.save(update_fields=["status"])
            messages.success(request, f"Recommendation #{rec.id} acknowledged.")
        return redirect("alerts:recommendations")

    return render(
        request, "alerts/recommendations.html", {"recommendations": recommendations}
    )
