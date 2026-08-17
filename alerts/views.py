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

        def number(field, default, cast=float):
            try:
                return cast(request.POST.get(field, default))
            except (TypeError, ValueError):
                return cast(default)

        profile.psi_moderate = number("psi_moderate", 0.10)
        profile.psi_high = number("psi_high", 0.25)
        profile.jsd_moderate = number("jsd_moderate", 0.10)
        profile.jsd_high = number("jsd_high", 0.20)
        profile.alpha = number("alpha", 0.05)
        profile.moderate_ratio_for_high = number("moderate_ratio_for_high", 0.30)
        profile.min_samples = number("min_samples", 30, int)
        profile.missing_value_rate_threshold = number(
            "missing_value_rate_threshold", 0.05
        )
        profile.duplicate_row_rate_threshold = number(
            "duplicate_row_rate_threshold", 0.01
        )
        profile.outlier_rate_threshold = number("outlier_rate_threshold", 0.05)
        profile.accuracy_drop_minor = number("accuracy_drop_minor", 0.05)
        profile.accuracy_drop_major = number("accuracy_drop_major", 0.10)
        profile.health_warning_threshold = number("health_warning_threshold", 80, int)
        profile.health_critical_threshold = number("health_critical_threshold", 60, int)
        profile.alert_cooldown_minutes = number("alert_cooldown_minutes", 60, int)
        profile.email_enabled = request.POST.get("email_enabled") == "on"

        # A moderate band above its high band would make MODERATE unreachable,
        # which is exactly the failure this whole two-band structure exists to
        # prevent. Reject rather than silently store it.
        if (
            profile.psi_moderate >= profile.psi_high
            or profile.jsd_moderate >= profile.jsd_high
        ):
            messages.error(
                request,
                "The moderate threshold must be below the high threshold for both "
                "PSI and JSD, otherwise no batch can ever be reported as moderate.",
            )
            return redirect("alerts:thresholds", slug=ml_model.slug)
        if profile.health_critical_threshold >= profile.health_warning_threshold:
            messages.error(
                request,
                "The critical health score must be below the warning score.",
            )
            return redirect("alerts:thresholds", slug=ml_model.slug)

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
