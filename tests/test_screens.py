"""Render tests for the monitoring screens — S8, S13, S14, S15.

A view that raises on a real run is worse than one that is missing, so these
exercise the templates against genuine data rather than checking status codes
on empty fixtures.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from core.constants import Permission, Role
from tests.conftest import drifted, holdout
from monitoring.services import ingest_batch

pytestmark = pytest.mark.django_db


@pytest.fixture
def run_with_drift(churn_model):
    ml_model, version, owner = churn_model
    return ingest_batch(ml_model, drifted()), ml_model, owner


def test_run_detail_renders_the_whole_result(client, run_with_drift):
    run, ml_model, owner = run_with_drift
    client.force_login(owner)

    response = client.get(reverse("monitoring:run_detail", args=[run.pk]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "MonthlyCharges" in body
    assert "Feature drift" in body
    assert "How this health score was reached" in body
    # Status is never colour alone — the badge carries an icon and a label.
    assert 'aria-label="High"' in body
    assert "Data quality" in body


def test_run_detail_table_can_be_sorted(client, run_with_drift):
    run, _, owner = run_with_drift
    client.force_login(owner)
    for sort in ("feature", "psi", "pvalue", "status"):
        response = client.get(
            reverse("monitoring:run_detail", args=[run.pk]), {"sort": sort}
        )
        assert response.status_code == 200, sort


def test_feature_detail_shows_the_explanation(client, run_with_drift):
    """FR-14 — the differentiating feature, on screen."""
    run, _, owner = run_with_drift
    client.force_login(owner)

    response = client.get(
        reverse("monitoring:feature_detail", args=[run.pk, "MonthlyCharges"])
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Why this is flagged" in body
    assert "High drift detected" in body
    assert "PSI is" in body


def test_feature_distribution_api_returns_chartable_data(client, run_with_drift):
    run, _, owner = run_with_drift
    client.force_login(owner)

    numeric = client.get(
        reverse("monitoring:feature_distribution_api", args=[run.pk, "MonthlyCharges"])
    ).json()
    assert numeric["type"] == "numeric"
    assert len(numeric["labels"]) == len(numeric["baseline"]) == len(numeric["current"])
    assert sum(numeric["current"]) > 0

    categorical = client.get(
        reverse("monitoring:feature_distribution_api", args=[run.pk, "Contract"])
    ).json()
    assert categorical["type"] == "categorical"
    assert "Month-to-month" in categorical["labels"]


def test_run_status_api_is_pollable(client, run_with_drift):
    run, _, owner = run_with_drift
    client.force_login(owner)
    payload = client.get(reverse("monitoring:run_status", args=[run.pk])).json()

    assert payload["status"] == "COMPLETED"
    assert payload["health_band"]
    assert payload["detail_url"].endswith(f"/runs/{run.pk}/")


def test_runs_of_an_ungranted_model_are_unreachable(client, run_with_drift):
    """FR-01.7 — and indistinguishable from a run that does not exist."""
    from accounts.models import User

    run, _, _ = run_with_drift
    outsider = User.objects.create_user(username="out", password="p", role=Role.ANALYST)
    client.force_login(outsider)

    assert (
        client.get(reverse("monitoring:run_detail", args=[run.pk])).status_code == 404
    )


def test_batch_upload_screen_lists_required_columns(client, churn_model):
    ml_model, _, owner = churn_model
    client.force_login(owner)

    response = client.get(reverse("datasets:batch_upload", args=[ml_model.slug]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "MonthlyCharges" in body
    assert "rejected rather than partly processed" in body


def test_analyst_can_upload_a_batch_but_not_a_baseline(client, churn_model):
    """PRD §5.2 — feeding production data in is the Analyst's job; defining
    the reference the model is judged against is not."""
    from accounts.models import User, ModelAccess

    ml_model, _, owner = churn_model
    engineer = User.objects.create_user(username="eng", password="p", role=Role.ANALYST)
    ModelAccess.objects.create(
        user=engineer, ml_model=ml_model, permission=Permission.VIEW
    )
    client.force_login(engineer)

    assert (
        client.get(reverse("datasets:batch_upload", args=[ml_model.slug])).status_code
        == 200
    )

    from django.core.exceptions import PermissionDenied

    try:
        response = client.get(reverse("datasets:baseline_upload", args=[ml_model.slug]))
        assert response.status_code in (403, 404)
    except PermissionDenied:
        pass


def test_uploading_a_batch_end_to_end_through_the_form(client, churn_model):
    """The real S15 path: a CSV posted to the view produces a run."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    ml_model, _, owner = churn_model
    client.force_login(owner)

    csv_bytes = holdout(200).to_csv(index=False).encode()
    response = client.post(
        reverse("datasets:batch_upload", args=[ml_model.slug]),
        {"batch": SimpleUploadedFile("batch.csv", csv_bytes, content_type="text/csv")},
        follow=True,
    )

    assert response.status_code == 200
    assert ml_model.runs.count() == 1
    run = ml_model.runs.first()
    assert run.status == "COMPLETED"
    assert run.data_batch.source == "UPLOAD"
    assert run.data_batch.submitted_by == owner
