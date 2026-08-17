import pytest
from django.urls import reverse
from accounts.models import User
from registry.models import MLModel
from core.constants import Role, ProblemType


@pytest.mark.django_db
def test_chart_endpoints_and_downsampling(client):
    user = User.objects.create_user(
        username="chartuser", password="p", role=Role.ML_ENGINEER
    )
    client.login(username="chartuser", password="p")

    model = MLModel.objects.create(
        name="Chart Model",
        slug="chart-model",
        target_column="target",
        problem_type=ProblemType.BINARY,
        owner=user,
    )

    # 1. Performance chart API
    url_perf = reverse("dashboard:chart_performance", kwargs={"slug": model.slug})
    resp = client.get(url_perf)
    assert resp.status_code == 200
    json_data = resp.json()
    assert "series" in json_data
    assert len(json_data["timestamps"]) <= 500

    # 2. Drift chart API
    url_drift = reverse("dashboard:chart_drift", kwargs={"slug": model.slug})
    resp_drift = client.get(url_drift)
    assert resp_drift.status_code == 200
    assert "ks" in resp_drift.json()["series"]

    # 3. Distribution API
    url_dist = reverse("dashboard:chart_distribution", kwargs={"slug": model.slug})
    assert client.get(url_dist).status_code == 200

    # 4. Prediction trend API
    url_pred = reverse("dashboard:chart_prediction_trend", kwargs={"slug": model.slug})
    assert client.get(url_pred).status_code == 200

    # 5. Alerts trend API
    url_alerts = reverse("dashboard:chart_alerts_trend", kwargs={"slug": model.slug})
    assert client.get(url_alerts).status_code == 200

    # 6. Health trend API
    url_health = reverse("dashboard:chart_health_trend", kwargs={"slug": model.slug})
    assert client.get(url_health).status_code == 200

    # 7. Feature distribution API
    url_feat = reverse(
        "dashboard:chart_feature_distribution",
        kwargs={"slug": model.slug, "feature_name": "tenure"},
    )
    assert client.get(url_feat).status_code == 200
