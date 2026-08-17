from django.urls import path
from registry import views

app_name = "registry"

urlpatterns = [
    path("", views.model_list_view, name="list"),
    path("new/", views.model_create_edit_view, name="create"),
    path("<slug:slug>/", views.model_overview_view, name="overview"),
    path("<slug:slug>/edit/", views.model_create_edit_view, name="edit"),
    path("<slug:slug>/versions/", views.model_versions_view, name="versions"),
    path("<slug:slug>/train/", views.model_train_view, name="train"),
    path(
        "<slug:slug>/versions/new/",
        views.model_version_upload_view,
        name="version_upload",
    ),
    path(
        "<slug:slug>/versions/<int:version_id>/activate/",
        views.model_version_activate_view,
        name="version_activate",
    ),
    path("<slug:slug>/compare/", views.version_comparison_view, name="compare"),
    path("<slug:slug>/history/", views.monitoring_history_view, name="history"),
    path(
        "<slug:slug>/history/export/",
        views.history_csv_export_view,
        name="history_export",
    ),
]
