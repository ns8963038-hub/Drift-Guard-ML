import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import User
from registry.models import MLModel, ModelVersion, ModelAuditLog
from registry.services import create_model_version, activate_version
from core.constants import Role, VersionStatus, ProblemType, ValidationStatus


@pytest.mark.django_db
def test_create_model_and_audit(client):
    # Data Scientist, not ML Engineer. PRD §5.2 forbids an ML Engineer from
    # creating models; this test previously used one and asserted success,
    # which locked the missing role check in as expected behaviour.
    user = User.objects.create_user(
        username="creator", password="p", role=Role.DATA_SCIENTIST
    )
    client.login(username="creator", password="p")

    url = reverse("registry:create")
    response = client.post(
        url,
        {
            "name": "Churn Model",
            "description": "Predicts customer churn",
            "target_column": "Churn",
            "problem_type": ProblemType.BINARY,
        },
    )
    assert response.status_code == 302

    model = MLModel.objects.get(slug="churn-model")
    assert model.name == "Churn Model"
    assert model.owner == user

    # Check Audit Log
    audit = ModelAuditLog.objects.filter(ml_model=model).first()
    assert audit is not None
    assert audit.action == "MODEL_CREATED"


@pytest.mark.django_db
def test_validation_gate_rejects_corrupt_file(client):
    user = User.objects.create_user(username="dev", password="p", role=Role.ML_ENGINEER)
    model = MLModel.objects.create(
        name="Test Model",
        slug="test-model",
        target_column="target",
        problem_type=ProblemType.BINARY,
        owner=user,
    )

    corrupt_file = SimpleUploadedFile("corrupt.pkl", b"invalid binary content")

    with pytest.raises(Exception) as exc_info:
        create_model_version(model, corrupt_file, label="V1", user=user)

    assert "Check 1 Failed" in str(exc_info.value)
    # Ensure NO version row was created
    assert ModelVersion.objects.filter(ml_model=model).count() == 0


@pytest.mark.django_db
def test_version_activation_single_active_constraint(client):
    user = User.objects.create_user(
        username="dev2", password="p", role=Role.ML_ENGINEER
    )
    model = MLModel.objects.create(
        name="Model X",
        slug="model-x",
        target_column="target",
        problem_type=ProblemType.BINARY,
        owner=user,
    )

    v1 = ModelVersion.objects.create(
        ml_model=model,
        version_number=1,
        label="V1",
        status=VersionStatus.INACTIVE,
        validation_status=ValidationStatus.PASSED,
    )
    v2 = ModelVersion.objects.create(
        ml_model=model,
        version_number=2,
        label="V2",
        status=VersionStatus.INACTIVE,
        validation_status=ValidationStatus.PASSED,
    )

    # Activate V1
    activate_version(v1, user=user)
    v1.refresh_from_db()
    assert v1.status == VersionStatus.ACTIVE

    # Activate V2 -> V1 demoted to INACTIVE in one transaction
    activate_version(v2, user=user)
    v1.refresh_from_db()
    v2.refresh_from_db()

    assert v1.status == VersionStatus.INACTIVE
    assert v2.status == VersionStatus.ACTIVE
    assert model.active_version == v2
