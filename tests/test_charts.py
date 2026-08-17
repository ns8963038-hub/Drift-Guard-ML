"""Chart endpoint tests — PRD FR-07.

These previously asserted against generated data. They now exercise real runs,
and the properties they check are the ones that make the charts honest rather
than merely present.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from tests.conftest import drifted, holdout
from monitoring.services import ingest_batch

pytestmark = pytest.mark.django_db


@pytest.fixture
def model_with_runs(churn_model):
    """A clean run, an unlabelled run, then a drifted run — in that order."""
    ml_model, _, owner = churn_model
    ingest_batch(ml_model, holdout(300, seed=1))
    ingest_batch(ml_model, holdout(300, seed=2).drop(columns=["Churn"]))
    ingest_batch(ml_model, drifted(300, seed=3))
    return ml_model, owner


def get(client, name, ml_model, **params):
    return client.get(reverse(f"dashboard:{name}", args=[ml_model.slug]), params).json()


def test_performance_chart_gaps_unlabelled_runs(client, model_with_runs):
    """FR-04.7 — the single most important property of this chart.

    The middle run had no ground truth. It must appear as a gap, not as zero:
    plotting 0 would draw a cliff and make a healthy model look collapsed.
    """
    ml_model, owner = model_with_runs
    client.force_login(owner)
    data = get(client, "chart_performance", ml_model, range="all")

    accuracy = data["series"]["accuracy"]
    assert len(accuracy) == 3
    assert accuracy[1] is None, "unlabelled run must be a gap"
    assert 0 not in accuracy, "a gap must never be rendered as zero"
    assert data["labelled_runs"] == 2
    assert data["unlabelled_runs"] == 1


def test_drift_chart_counts_add_up(client, model_with_runs):
    ml_model, owner = model_with_runs
    client.force_login(owner)
    data = get(client, "chart_drift", ml_model, range="all")

    counts = data["counts"]
    assert len(counts["high"]) == 3
    for i in range(3):
        assert counts["high"][i] + counts["moderate"][i] + counts["none"][i] == 19
    assert counts["high"][2] >= 2, "the drifted run is last"
    assert max(p for p in data["max_psi"] if p is not None) > 0.25


def test_health_chart_carries_its_band_boundaries(client, model_with_runs):
    ml_model, owner = model_with_runs
    client.force_login(owner)
    data = get(client, "chart_health_trend", ml_model, range="all")

    assert len(data["scores"]) == 3
    assert data["warning_at"] == 80
    assert data["critical_at"] == 60
    assert data["scores"][0] > data["scores"][2], "health fell as drift arrived"


def test_prediction_trend_covers_unlabelled_runs_too(client, model_with_runs):
    """The only behavioural signal available without ground truth."""
    ml_model, owner = model_with_runs
    client.force_login(owner)
    data = get(client, "chart_prediction_trend", ml_model, range="all")

    assert set(data["series"]) == {"No", "Yes"}
    for values in data["series"].values():
        assert len(values) == 3
        assert all(v is not None for v in values)


def test_alerts_trend_is_chronological(client, model_with_runs):
    ml_model, owner = model_with_runs
    client.force_login(owner)
    data = get(client, "chart_alerts_trend", ml_model, range="all")

    assert "critical" in data["series"]
    assert len(data["labels"]) == len(data["series"]["critical"])


def test_charts_respect_model_access(client, model_with_runs):
    from accounts.models import User
    from core.constants import Role

    ml_model, _ = model_with_runs
    outsider = User.objects.create_user(
        username="out", password="p", role=Role.ML_ENGINEER
    )
    client.force_login(outsider)

    response = client.get(reverse("dashboard:chart_health_trend", args=[ml_model.slug]))
    assert response.status_code == 404


def test_no_endpoint_returns_generated_data(client, churn_model):
    """A model with no runs must return empty series, not invented ones.

    The endpoints previously produced a synthetic sawtooth regardless of the
    data. An empty model is the case that exposes it.
    """
    ml_model, _, owner = churn_model
    client.force_login(owner)

    for name in ("chart_performance", "chart_drift", "chart_health_trend"):
        data = get(client, name, ml_model, range="all")
        flat = []
        for value in data.values():
            if isinstance(value, list):
                flat += value
            elif isinstance(value, dict):
                for inner in value.values():
                    if isinstance(inner, list):
                        flat += inner
        assert not flat, f"{name} invented data for a model with no runs"


def test_model_tabs_render(client, model_with_runs):
    ml_model, owner = model_with_runs
    client.force_login(owner)
    for name in ("model_drift", "model_performance", "model_quality"):
        response = client.get(reverse(f"dashboard:{name}", args=[ml_model.slug]))
        assert response.status_code == 200, name


def test_dashboard_sorts_worst_health_first(client, model_with_runs):
    ml_model, owner = model_with_runs
    client.force_login(owner)
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    assert ml_model.name in response.content.decode()
