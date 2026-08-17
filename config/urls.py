from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("dashboard.urls")),
    path("", include("accounts.urls")),
    path("models/", include("registry.urls")),
    path("alerts/", include("alerts.urls")),
    path("models/", include("datasets.urls")),
    path("", include("monitoring.urls")),
]
