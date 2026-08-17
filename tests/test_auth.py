import pytest
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, LoginActivity
from core.constants import Role, LoginEvent


@pytest.mark.django_db
def test_login_success(client):
    User.objects.create_user(
        username="testuser", password="password123", role=Role.ANALYST
    )
    url = reverse("accounts:login")
    response = client.post(url, {"username": "testuser", "password": "password123"})
    assert response.status_code == 302
    assert response.url == reverse("dashboard:index")

    # Verify LoginActivity recorded
    activity = LoginActivity.objects.first()
    assert activity is not None
    assert activity.username_attempted == "testuser"
    assert activity.event == LoginEvent.LOGIN_SUCCESS


@pytest.mark.django_db
def test_login_failed_lockout(client):
    user = User.objects.create_user(
        username="lockoutuser", password="password123", role=Role.ANALYST
    )
    url = reverse("accounts:login")

    # 4 failed attempts
    for _ in range(4):
        response = client.post(
            url, {"username": "lockoutuser", "password": "wrongpassword"}
        )
        assert response.status_code == 200

    user.refresh_from_db()
    assert user.failed_login_count == 4
    assert user.locked_until is None

    # 5th failed attempt -> locks user
    response = client.post(
        url, {"username": "lockoutuser", "password": "wrongpassword"}
    )
    assert response.status_code == 200

    user.refresh_from_db()
    assert user.failed_login_count == 5
    assert user.locked_until is not None
    assert user.locked_until > timezone.now()


@pytest.mark.django_db
def test_logout(client):
    User.objects.create_user(
        username="logoutuser", password="password123", role=Role.ANALYST
    )
    client.login(username="logoutuser", password="password123")
    url = reverse("accounts:logout")
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == reverse("accounts:login")

    # Verify Logout event recorded
    activity = LoginActivity.objects.filter(event=LoginEvent.LOGOUT).first()
    assert activity is not None
    assert activity.username_attempted == "logoutuser"
