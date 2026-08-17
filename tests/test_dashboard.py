"""Dashboard rendering — the screen every session starts on."""

import pytest
from django.urls import reverse

from accounts.models import User
from core.constants import Role


@pytest.mark.django_db
def test_admin_dashboard_survives_a_failed_login_for_an_unknown_account(client):
    """The audit panel used `|default:entry.user.username`.

    Django resolves a filter argument eagerly, so a LoginActivity with no user —
    a failed sign-in for an account that does not exist, precisely what the
    audit trail exists to record — raised VariableDoesNotExist and returned 500.
    """
    from accounts.models import LoginActivity

    admin = User.objects.create_user(username="adm", password="p", role=Role.ADMIN)
    LoginActivity.objects.create(
        user=None, username_attempted="attacker", event="LOGIN_FAILED"
    )
    # An event with neither a user nor an attempted name must not break it either.
    LoginActivity.objects.create(user=None, username_attempted="", event="LOGOUT")

    client.force_login(admin)
    response = client.get(reverse("dashboard:index"))

    assert response.status_code == 200
    assert "attacker" in response.content.decode()
