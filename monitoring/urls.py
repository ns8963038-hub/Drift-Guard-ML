from django.urls import path

from monitoring import views

app_name = "monitoring"

urlpatterns = [
    path("runs/<int:run_id>/", views.run_detail_view, name="run_detail"),
    path("runs/<int:run_id>/status/", views.run_status_api, name="run_status"),
    path(
        "runs/<int:run_id>/features/<str:feature_name>/",
        views.feature_detail_view,
        name="feature_detail",
    ),
    path(
        "api/runs/<int:run_id>/features/<str:feature_name>/distribution/",
        views.feature_distribution_api,
        name="feature_distribution_api",
    ),
]
