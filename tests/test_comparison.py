import pytest
from django.urls import reverse
from accounts.models import User
from registry.models import MLModel, ModelVersion
from core.constants import Role, ProblemType, VersionStatus, ValidationStatus


@pytest.mark.django_db
def test_version_comparison_and_csv_export(client):
    user = User.objects.create_user(
        username="compuser", password="p", role=Role.ML_ENGINEER
    )
    client.login(username="compuser", password="p")

    model = MLModel.objects.create(
        name="Telco Model",
        slug="telco-model",
        target_column="Churn",
        problem_type=ProblemType.BINARY,
        owner=user,
    )

    v1 = ModelVersion.objects.create(
        ml_model=model,
        version_number=1,
        label="V1",
        status=VersionStatus.INACTIVE,
        validation_status=ValidationStatus.PASSED,
        feature_schema={"tenure": "numeric"},
        training_accuracy=0.78,
    )
    v2 = ModelVersion.objects.create(
        ml_model=model,
        version_number=2,
        label="V2",
        status=VersionStatus.ACTIVE,
        validation_status=ValidationStatus.PASSED,
        feature_schema={"tenure": "numeric"},
        training_accuracy=0.85,
    )

    # 1. Version comparison page
    url_comp = reverse("registry:compare", kwargs={"slug": model.slug})
    resp = client.get(f"{url_comp}?v1={v1.id}&v2={v2.id}")
    assert resp.status_code == 200
    assert "outperforms" in resp.context["verdict"]

    # 2. History page
    url_hist = reverse("registry:history", kwargs={"slug": model.slug})
    assert client.get(url_hist).status_code == 200

    # 3. CSV export page
    url_csv = reverse("registry:history_export", kwargs={"slug": model.slug})
    resp_csv = client.get(url_csv)
    assert resp_csv.status_code == 200
    assert resp_csv["Content-Type"] == "text/csv"
    assert b"Run ID,Model,Timestamp" in resp_csv.content
