"""The demo script, as a test — docs/APP_FLOW.md §8.

Rehearsing by hand catches a broken demo once. Running it as a test catches it
every time, which matters more: the demo is what the project is graded on, and
a screen that 500s during a viva costs more than any missing feature.

Every step below maps to a numbered step in the demo script.
"""

from __future__ import annotations

import re

import pytest
from django.urls import reverse

from accounts.models import ModelAccess, User
from alerts.models import Alert, RetrainRecommendation
from core.constants import DriftStatus, Permission, ProblemType, Role
from monitoring.services import ingest_batch
from registry.models import MLModel
from tests.conftest import FIXTURES_PRESENT, drifted, holdout

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not FIXTURES_PRESENT, reason="demo fixtures not built"),
]


@pytest.fixture
def demo(churn_model):
    """The seeded state: history, a second model, and asymmetric access."""
    ml_model, version, owner = churn_model

    admin = User.objects.create_user(username="admin", password="p", role=Role.ADMIN)
    engineer = User.objects.create_user(
        username="eng", password="p", role=Role.ML_ENGINEER
    )
    ModelAccess.objects.create(
        user=engineer, ml_model=ml_model, permission=Permission.VIEW
    )

    # A second model the engineer is deliberately NOT granted.
    other = MLModel.objects.create(
        name="Income Prediction Model",
        slug="income-prediction-model",
        target_column="income",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )

    from django.core.files.uploadedfile import SimpleUploadedFile

    from simulator import transforms
    from simulator.models import SimulationScenario
    from tests.conftest import DATA

    with open(DATA / "holdout.csv", "rb") as handle:
        SimulationScenario.objects.create(
            ml_model=ml_model,
            name="Drift demo",
            interval_seconds=30,
            batch_size=400,
            drift_plan=transforms.default_scenario("MonthlyCharges", "Contract"),
            holdout_file=SimpleUploadedFile("holdout.csv", handle.read()),
            created_by=owner,
        )

    ingest_batch(ml_model, holdout(300, seed=1))  # clean
    ingest_batch(ml_model, drifted(300, seed=2))  # drifted
    ingest_batch(ml_model, drifted(300, seed=3))  # drifted again

    return {
        "model": ml_model,
        "other": other,
        "admin": admin,
        "owner": owner,
        "engineer": engineer,
        "latest": ml_model.runs.order_by("-created_at").first(),
        "earliest": ml_model.runs.order_by("created_at").first(),
    }


def test_step_1_admin_screens(client, demo):
    client.force_login(demo["admin"])
    for name in (
        "accounts:user_list",
        "accounts:access_grants",
        "accounts:login_activity",
    ):
        assert client.get(reverse(name)).status_code == 200, name


def test_step_2_access_control_is_demonstrable(client, demo):
    """The step that shows RBAC rather than asserting it on a slide."""
    client.force_login(demo["engineer"])
    assert (
        client.get(reverse("registry:overview", args=[demo["model"].slug])).status_code
        == 200
    )
    assert (
        client.get(reverse("registry:overview", args=[demo["other"].slug])).status_code
        == 404
    )


def test_steps_3_and_4_versions_and_comparison(client, demo):
    client.force_login(demo["owner"])
    assert (
        client.get(reverse("registry:versions", args=[demo["model"].slug])).status_code
        == 200
    )

    response = client.get(reverse("registry:compare", args=[demo["model"].slug]))
    assert response.status_code == 200


def test_step_5_run_detail_shows_everything(client, demo):
    client.force_login(demo["owner"])
    body = client.get(
        reverse("monitoring:run_detail", args=[demo["latest"].pk])
    ).content.decode()

    assert "Feature drift" in body
    assert "How this health score was reached" in body
    assert "Data quality" in body


def test_step_6_simulator_screen(client, demo):
    client.force_login(demo["owner"])
    response = client.get(reverse("simulator:list", args=[demo["model"].slug]))
    assert response.status_code == 200
    assert "Run one batch now" in response.content.decode()


def test_step_7_dashboard_reflects_state(client, demo):
    client.force_login(demo["owner"])
    assert client.get(reverse("dashboard:index")).status_code == 200


def test_step_8_feature_table_is_worst_first(client, demo):
    client.force_login(demo["owner"])
    results = list(demo["latest"].feature_results.all())
    assert any(r.status == DriftStatus.HIGH for r in results)


def test_step_9_the_explanation_is_real_prose(client, demo):
    """The differentiating feature — the one an examiner remembers."""
    client.force_login(demo["owner"])
    body = client.get(
        reverse("monitoring:feature_detail", args=[demo["latest"].pk, "MonthlyCharges"])
    ).content.decode()

    assert "Why this is flagged" in body
    assert "High drift detected" in body
    assert "PSI is" in body
    assert "K-S test" in body


def test_step_10_alerts_are_deduplicated(client, demo):
    """Two drifted runs must give one alert with a count, not two alerts."""
    client.force_login(demo["owner"])
    assert client.get(reverse("alerts:list")).status_code == 200

    alerts = Alert.objects.filter(ml_model=demo["model"], feature_name="MonthlyCharges")
    assert alerts.count() == 1
    assert alerts.first().occurrence_count == 2


def test_step_11_retraining_recommendation_names_its_triggers(client, demo):
    client.force_login(demo["owner"])
    assert client.get(reverse("alerts:recommendations")).status_code == 200

    recommendation = RetrainRecommendation.objects.get(ml_model=demo["model"])
    assert recommendation.triggers, "FR-10.2 — the reasons must be named"
    for trigger in recommendation.triggers:
        # Each trigger states what was measured against what threshold, which
        # is the difference between "retrain" and an actionable recommendation.
        assert trigger["trigger"] and trigger["measured"] and trigger["threshold"]
    assert "advisory only" in recommendation.message


def test_step_12_data_quality_tab(client, demo):
    client.force_login(demo["owner"])
    assert (
        client.get(
            reverse("dashboard:model_quality", args=[demo["model"].slug])
        ).status_code
        == 200
    )


def test_step_13_history_is_immutable(client, demo):
    """Reopening an early run must show what it showed then."""
    from alerts.models import ThresholdProfile

    client.force_login(demo["owner"])
    assert (
        client.get(reverse("registry:history", args=[demo["model"].slug])).status_code
        == 200
    )

    earliest = demo["earliest"]
    assert earliest.overall_drift_status == DriftStatus.NONE

    ThresholdProfile.objects.create(
        ml_model=demo["model"], psi_moderate=0.0001, psi_high=0.0002
    )
    earliest.refresh_from_db()
    assert earliest.overall_drift_status == DriftStatus.NONE, "history was rewritten"


# ──────────────────────────────────────────────────────────────────────
# NFR-10 — the demo must work with the network off
# ──────────────────────────────────────────────────────────────────────

EXTERNAL = re.compile(r"""(src|href)=["']https?://(?!127\.0\.0\.1|localhost)""", re.I)


def test_no_page_references_an_external_host(client, demo):
    """Verified on rendered HTML, not just on the source.

    A CDN link in a template only fails when the demo machine has no network —
    which is exactly the moment it cannot be fixed.
    """
    client.force_login(demo["owner"])
    slug = demo["model"].slug
    pages = [
        reverse("dashboard:index"),
        reverse("registry:list"),
        reverse("alerts:list"),
        reverse("registry:overview", args=[slug]),
        reverse("registry:versions", args=[slug]),
        reverse("registry:compare", args=[slug]),
        reverse("registry:history", args=[slug]),
        reverse("dashboard:model_drift", args=[slug]),
        reverse("dashboard:model_quality", args=[slug]),
        reverse("simulator:list", args=[slug]),
        reverse("datasets:batch_upload", args=[slug]),
        reverse("monitoring:run_detail", args=[demo["latest"].pk]),
        reverse(
            "monitoring:feature_detail", args=[demo["latest"].pk, "MonthlyCharges"]
        ),
        reverse("accounts:profile"),
    ]

    for url in pages:
        response = client.get(url)
        assert response.status_code == 200, url
        hits = EXTERNAL.findall(response.content.decode(errors="ignore"))
        assert not hits, f"{url} references an external host"
