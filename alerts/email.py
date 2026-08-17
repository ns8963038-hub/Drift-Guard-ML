import logging
from django.conf import settings
from django.core.mail import send_mail
from core.constants import AlertSeverity

logger = logging.getLogger(__name__)


def send_alert_email(alert):
    """
    Sends email notification for CRITICAL severity alerts.
    Failures logged and swallowed — never raises exceptions.
    """
    if not getattr(settings, "EMAIL_ENABLED", False):
        return False

    if alert.severity != AlertSeverity.CRITICAL:
        return False

    try:
        subject = f"[CRITICAL ALERT] {alert.ml_model.name}: {alert.headline}"
        message = (
            f"Alert ID: {alert.id}\n"
            f"Model: {alert.ml_model.name}\n"
            f"Category: {alert.category}\n"
            f"Feature: {alert.feature_name or 'N/A'}\n\n"
            f"Details:\n{alert.message}\n"
        )
        recipient_list = (
            [alert.ml_model.owner.email] if alert.ml_model.owner.email else []
        )
        if recipient_list:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(
                    settings, "DEFAULT_FROM_EMAIL", "noreply@driftguard.local"
                ),
                recipient_list=recipient_list,
                fail_silently=False,
            )
            return True
    except Exception as e:
        logger.warning(
            f"Alert email delivery failed silently for Alert #{alert.id}: {str(e)}"
        )
        return False

    return False
