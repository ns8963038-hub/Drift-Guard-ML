"""Context available to every template.

Role-dependent navigation needs to know what the current user may do on *every*
page, not just the ones that happen to pass it in. Computing it once here is
what lets the interface hide actions a user cannot take, rather than showing
them and rejecting the click.
"""

from alerts.models import Alert
from core.constants import AlertStatus, Role


def navigation(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    is_admin = user.role == Role.ADMIN or user.is_superuser
    is_scientist = user.role == Role.DATA_SCIENTIST

    from core.mixins import visible_models

    models = visible_models(user)

    return {
        # Capability flags, named for what they permit rather than for a role,
        # so a template reads as "can this user do X" and stays correct if the
        # permission matrix changes.
        "can_manage_users": is_admin,
        "can_create_models": is_admin or is_scientist,
        "can_manage_models": is_admin or is_scientist,
        "role_label": user.get_role_display(),
        "role_slug": user.role.lower(),
        "nav_model_count": models.count(),
        "nav_alert_count": Alert.objects.filter(
            ml_model__in=models,
            status__in=[AlertStatus.NEW, AlertStatus.ACKNOWLEDGED],
        ).count(),
    }
