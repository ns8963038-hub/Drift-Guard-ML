"""In-platform training — the synopsis "Train Model" use case.

The client's college synopsis specifies that the system trains a supervised
model from historical data and reports baseline accuracy, precision and recall.
These verify that path end to end, and that a model trained here is immediately
monitorable — which is the point of having it.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import User
from core.constants import ProblemType, Role, VersionStatus
from monitoring.services import ingest_batch
from registry.models import MLModel
from registry.training import ALGORITHMS, train_and_register
from tests.conftest import DATA, FIXTURES_PRESENT, holdout

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not FIXTURES_PRESENT, reason="demo fixtures not built"),
]


@pytest.fixture
def blank_model(tmp_path, settings):
    """A model with no versions and no baseline — the state before training."""
    settings.MEDIA_ROOT = str(tmp_path)
    owner = User.objects.create_user(
        username="ds", password="p", role=Role.DATA_SCIENTIST
    )
    ml_model = MLModel.objects.create(
        name="Churn",
        slug="churn",
        target_column="Churn",
        positive_class="Yes",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )
    return ml_model, owner


def training_csv():
    with open(DATA / "baseline.csv", "rb") as handle:
        return SimpleUploadedFile("training.csv", handle.read())


def test_training_produces_a_usable_version(blank_model):
    ml_model, owner = blank_model
    version, metrics = train_and_register(
        ml_model, training_csv(), "logistic_regression", "Churn", user=owner
    )

    assert version.status == VersionStatus.ACTIVE
    assert version.label == "V1"
    assert version.algorithm_name == "Logistic Regression"
    assert version.artifact
    assert version.validation_status == "PASSED"

    # Synopsis §9 expects a baseline accuracy in the 75–85% band.
    assert 0.70 < metrics["accuracy"] < 0.90
    assert metrics["precision"] > 0
    assert metrics["recall"] > 0


def test_training_also_creates_the_baseline(blank_model):
    """One upload sets everything up.

    A model must be monitored against the data it was trained on. Deriving both
    from the same file removes the commonest way to get that wrong.
    """
    ml_model, owner = blank_model
    version, metrics = train_and_register(
        ml_model, training_csv(), "decision_tree", "Churn", user=owner
    )

    baseline = version.baseline
    assert baseline is not None
    assert baseline.row_count == metrics["training_rows"]
    assert version.baseline_prediction_distribution


def test_a_trained_model_is_immediately_monitorable(blank_model):
    """The whole point: train, then feed it a batch, with nothing in between."""
    ml_model, owner = blank_model
    train_and_register(
        ml_model, training_csv(), "balanced_random_forest", "Churn", user=owner
    )

    run = ingest_batch(ml_model, holdout(300))

    assert run.status == "COMPLETED"
    assert run.features_total == 19
    assert run.performance.accuracy is not None
    assert run.health_score is not None


def test_every_offered_algorithm_trains(blank_model):
    ml_model, owner = blank_model
    for key in ALGORITHMS:
        model = MLModel.objects.create(
            name=f"M {key}",
            slug=f"m-{key}",
            target_column="Churn",
            positive_class="Yes",
            problem_type=ProblemType.BINARY,
            owner=owner,
        )
        _, metrics = train_and_register(model, training_csv(), key, "Churn", user=owner)
        assert metrics["accuracy"] > 0.5, key


def test_balanced_forest_beats_plain_on_recall(blank_model):
    """Why the balanced option is offered at all.

    The Telco target is 26.5% churn. Plain training optimises accuracy and misses
    roughly half the churners; the balanced variant trades a little accuracy for
    substantially better recall — which for churn is the metric that matters.
    """
    ml_model, owner = blank_model
    other = MLModel.objects.create(
        name="Churn B",
        slug="churn-b",
        target_column="Churn",
        positive_class="Yes",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )

    _, plain = train_and_register(
        ml_model, training_csv(), "random_forest", "Churn", user=owner
    )
    _, balanced = train_and_register(
        other, training_csv(), "balanced_random_forest", "Churn", user=owner
    )

    assert balanced["recall"] > plain["recall"]


def test_versions_increment_across_trainings(blank_model):
    ml_model, owner = blank_model
    v1, _ = train_and_register(
        ml_model, training_csv(), "logistic_regression", "Churn", user=owner
    )
    v2, _ = train_and_register(
        ml_model, training_csv(), "decision_tree", "Churn", user=owner
    )

    assert (v1.label, v2.label) == ("V1", "V2")
    v1.refresh_from_db()
    assert v1.status == VersionStatus.INACTIVE, "only one version may be active"
    assert v2.status == VersionStatus.ACTIVE


def test_bad_target_column_is_rejected(blank_model):
    ml_model, owner = blank_model
    with pytest.raises(ValidationError, match="not in the file"):
        train_and_register(
            ml_model, training_csv(), "decision_tree", "NoSuchColumn", user=owner
        )


def test_unknown_algorithm_is_rejected(blank_model):
    ml_model, owner = blank_model
    with pytest.raises(ValidationError, match="Unknown algorithm"):
        train_and_register(ml_model, training_csv(), "neural_net", "Churn", user=owner)


def test_training_screen_renders(client, blank_model):
    ml_model, owner = blank_model
    client.force_login(owner)
    response = client.get(reverse("registry:train", args=[ml_model.slug]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Logistic Regression" in body
    assert "Decision Tree" in body


def test_training_through_the_form(client, blank_model):
    ml_model, owner = blank_model
    client.force_login(owner)

    response = client.post(
        reverse("registry:train", args=[ml_model.slug]),
        {
            "dataset": training_csv(),
            "target_column": "Churn",
            "algorithm": "logistic_regression",
            "test_size": "0.25",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert ml_model.versions.count() == 1
    assert ml_model.versions.first().status == VersionStatus.ACTIVE


def test_analyst_cannot_train(client, blank_model):
    """PRD §5.2 — training is a Data Scientist action."""
    from django.core.exceptions import PermissionDenied

    ml_model, _ = blank_model
    analyst = User.objects.create_user(username="an", password="p", role=Role.ANALYST)
    client.force_login(analyst)

    try:
        response = client.get(reverse("registry:train", args=[ml_model.slug]))
        assert response.status_code in (403, 404)
    except PermissionDenied:
        pass
