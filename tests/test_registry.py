import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import User
from registry.models import MLModel, ModelVersion, ModelAuditLog
from registry.services import create_model_version, activate_version
from core.constants import Role, VersionStatus, ProblemType, ValidationStatus


@pytest.mark.django_db
def test_create_model_and_audit(client):
    # Data Scientist, not Analyst. PRD §5.2 forbids an Analyst from
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
    user = User.objects.create_user(username="dev", password="p", role=Role.ANALYST)
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
    user = User.objects.create_user(username="dev2", password="p", role=Role.ANALYST)
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


@pytest.mark.django_db
def test_blank_name_is_rejected_instead_of_creating_an_unreachable_model(client):
    """A model with an empty slug is unreachable at every /models/<slug>/ URL.

    The view took ``slugify(name)`` on trust. An empty or punctuation-only name
    slugifies to "", which the database accepts — producing a row that no URL
    in the application can ever resolve to.
    """
    User.objects.create_user(username="ds1", password="p", role=Role.DATA_SCIENTIST)
    client.login(username="ds1", password="p")
    url = reverse("registry:create")

    for bad_name in ["", "   ", "..."]:
        response = client.post(
            url,
            {
                "name": bad_name,
                "target_column": "Churn",
                "problem_type": ProblemType.BINARY,
            },
        )
        assert (
            response.status_code == 200
        ), f"{bad_name!r} should re-render, not redirect"
        assert not MLModel.objects.filter(slug="").exists()

    assert MLModel.objects.count() == 0


@pytest.mark.django_db
def test_missing_target_column_is_rejected(client):
    """Without a target column no run can score accuracy or exclude the label."""
    User.objects.create_user(username="ds2", password="p", role=Role.DATA_SCIENTIST)
    client.login(username="ds2", password="p")

    response = client.post(
        reverse("registry:create"),
        {"name": "No Target", "target_column": "", "problem_type": ProblemType.BINARY},
    )
    assert response.status_code == 200
    assert MLModel.objects.count() == 0


@pytest.mark.django_db
def test_rejected_submission_comes_back_filled_in(client):
    """A duplicate name used to return an empty form, discarding everything typed."""
    user = User.objects.create_user(
        username="ds3", password="p", role=Role.DATA_SCIENTIST
    )
    MLModel.objects.create(
        name="Churn Model",
        slug="churn-model",
        target_column="Churn",
        problem_type=ProblemType.BINARY,
        owner=user,
    )
    client.login(username="ds3", password="p")

    response = client.post(
        reverse("registry:create"),
        {
            "name": "Churn Model",
            "description": "A description worth not losing",
            "target_column": "Churn",
            "positive_class": "Yes",
            "problem_type": ProblemType.BINARY,
        },
    )
    body = response.content.decode()
    assert response.status_code == 200
    assert "already exists" in body
    assert "A description worth not losing" in body
    assert 'value="Churn Model"' in body
    assert 'value="Yes"' in body


@pytest.mark.django_db
def test_register_button_is_shown_only_to_roles_that_may_create(client):
    """The button linked to href="#", so it was visible to all and worked for none."""
    create_url = reverse("registry:create")

    User.objects.create_user(username="ds4", password="p", role=Role.DATA_SCIENTIST)
    client.login(username="ds4", password="p")
    assert create_url in client.get(reverse("registry:list")).content.decode()

    User.objects.create_user(username="an4", password="p", role=Role.ANALYST)
    client.login(username="an4", password="p")
    assert create_url not in client.get(reverse("registry:list")).content.decode()


@pytest.mark.django_db
def test_a_version_that_failed_validation_cannot_be_activated():
    """Activation checked nothing, so a broken artifact could become active.

    Every subsequent run would then load that artifact to score its batch and
    fail — with an error pointing at the batch rather than the artifact.
    """
    from django.core.exceptions import ValidationError
    from core.constants import ValidationStatus, VersionStatus
    from registry.models import ModelVersion
    from registry.services import activate_version

    user = User.objects.create_user(
        username="dsact", password="p", role=Role.DATA_SCIENTIST
    )
    model = MLModel.objects.create(
        name="Act",
        slug="act",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )
    broken = ModelVersion.objects.create(
        ml_model=model,
        label="V1",
        validation_status=ValidationStatus.FAILED,
        status=VersionStatus.INACTIVE,
    )

    with pytest.raises(ValidationError):
        activate_version(broken, user=user)

    broken.refresh_from_db()
    assert broken.status != VersionStatus.ACTIVE


@pytest.mark.django_db
def test_activation_refusal_is_shown_as_a_message_not_a_500(client):
    from core.constants import ValidationStatus, VersionStatus
    from registry.models import ModelVersion

    user = User.objects.create_user(
        username="dsact2", password="p", role=Role.DATA_SCIENTIST
    )
    model = MLModel.objects.create(
        name="Act2",
        slug="act2",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )
    broken = ModelVersion.objects.create(
        ml_model=model,
        label="V1",
        validation_status=ValidationStatus.FAILED,
        status=VersionStatus.INACTIVE,
    )
    client.login(username="dsact2", password="p")

    response = client.post(
        reverse("registry:version_activate", args=[model.slug, broken.id]), follow=True
    )
    assert response.status_code == 200
    assert "failed validation" in response.content.decode()
