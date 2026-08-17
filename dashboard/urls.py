from django.urls import path
from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_index, name="index"),
    path(
        "models/<slug:slug>/charts/performance/",
        views.chart_performance_api,
        name="chart_performance",
    ),
    path("models/<slug:slug>/charts/drift/", views.chart_drift_api, name="chart_drift"),
    path(
        "models/<slug:slug>/charts/distribution/",
        views.chart_distribution_api,
        name="chart_distribution",
    ),
    path(
        "models/<slug:slug>/charts/prediction-trend/",
        views.chart_prediction_trend_api,
        name="chart_prediction_trend",
    ),
    path(
        "models/<slug:slug>/charts/alerts-trend/",
        views.chart_alerts_trend_api,
        name="chart_alerts_trend",
    ),
    path(
        "models/<slug:slug>/charts/health-trend/",
        views.chart_health_trend_api,
        name="chart_health_trend",
    ),
    path(
        "models/<slug:slug>/features/<str:feature_name>/distribution/",
        views.chart_feature_distribution_api,
        name="chart_feature_distribution",
    ),
    path("models/<slug:slug>/drift/", views.model_drift_tab_view, name="model_drift"),
    path(
        "models/<slug:slug>/performance/",
        views.model_performance_tab_view,
        name="model_performance",
    ),
    path(
        "models/<slug:slug>/quality/",
        views.model_quality_tab_view,
        name="model_quality",
    ),
]
