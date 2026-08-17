from django.contrib.auth.signals import (
    user_logged_in,
    user_login_failed,
    user_logged_out,
)
from django.dispatch import receiver
from accounts.models import LoginActivity, User
from core.constants import LoginEvent


def get_client_ip(request):
    if not request:
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
def log_user_logged_in(sender, request, user, **kwargs):
    ip = get_client_ip(request)
    ua = request.META.get("HTTP_USER_AGENT", "") if request else ""
    LoginActivity.objects.create(
        user=user,
        username_attempted=user.username,
        event=LoginEvent.LOGIN_SUCCESS,
        ip_address=ip,
        user_agent=ua,
    )
    # Reset failed login count on successful login
    if user.failed_login_count > 0 or user.locked_until:
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_count", "locked_until"])


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get("username", "") if credentials else ""
    ip = get_client_ip(request)
    ua = request.META.get("HTTP_USER_AGENT", "") if request else ""

    user = User.objects.filter(username=username).first()
    LoginActivity.objects.create(
        user=user,
        username_attempted=username,
        event=LoginEvent.LOGIN_FAILED,
        ip_address=ip,
        user_agent=ua,
    )


@receiver(user_logged_out)
def log_user_logged_out(sender, request, user, **kwargs):
    if user and user.is_authenticated:
        ip = get_client_ip(request)
        ua = request.META.get("HTTP_USER_AGENT", "") if request else ""
        LoginActivity.objects.create(
            user=user,
            username_attempted=user.username,
            event=LoginEvent.LOGOUT,
            ip_address=ip,
            user_agent=ua,
        )
