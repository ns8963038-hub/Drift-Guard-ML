from django.urls import path
from alerts import views

app_name = "alerts"

urlpatterns = [
    path("", views.alert_list_view, name="list"),
    path("<int:alert_id>/", views.alert_detail_view, name="detail"),
    path(
        "<int:alert_id>/acknowledge/", views.alert_acknowledge_view, name="acknowledge"
    ),
    path("<int:alert_id>/resolve/", views.alert_resolve_view, name="resolve"),
    path("thresholds/<slug:slug>/", views.threshold_settings_view, name="thresholds"),
    path(
        "recommendations/", views.retrain_recommendations_view, name="recommendations"
    ),
]
