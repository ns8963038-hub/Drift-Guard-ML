import pytest
from django.urls import reverse
from accounts.models import User, ModelAccess
from registry.models import MLModel
from core.constants import Role, Permission, ProblemType
from core.mixins import visible_models


@pytest.mark.django_db
def test_visible_models():
    admin = User.objects.create_user(username="admin", password="p", role=Role.ADMIN)
    owner = User.objects.create_user(
        username="owner", password="p", role=Role.ML_ENGINEER
    )
    other = User.objects.create_user(
        username="other", password="p", role=Role.ML_ENGINEER
    )

    m1 = MLModel.objects.create(
        name="Model A",
        slug="model-a",
        target_column="churn",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )
    MLModel.objects.create(
        name="Model B",
        slug="model-b",
        target_column="income",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )

    # Admin sees all models
    assert visible_models(admin).count() == 2

    # Owner sees owned models
    assert visible_models(owner).count() == 2

    # Other sees 0 models
    assert visible_models(other).count() == 0

    # Grant Model A to other
    ModelAccess.objects.create(user=other, ml_model=m1, permission=Permission.VIEW)
    assert visible_models(other).count() == 1
    assert visible_models(other).first() == m1


@pytest.mark.django_db
def test_admin_user_list_access(client):
    User.objects.create_user(username="engineer", password="p", role=Role.ML_ENGINEER)
    User.objects.create_user(username="admin", password="p", role=Role.ADMIN)

    url = reverse("accounts:user_list")

    # ML Engineer gets 403
    client.login(username="engineer", password="p")
    response = client.get(url)
    assert response.status_code == 403

    # Admin gets 200
    client.login(username="admin", password="p")
    response = client.get(url)
    assert response.status_code == 200
