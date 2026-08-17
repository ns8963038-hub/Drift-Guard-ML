from django.urls import path

from simulator import views

app_name = "simulator"

urlpatterns = [
    path("<slug:slug>/simulator/", views.scenario_list_view, name="list"),
    path("<slug:slug>/simulator/new/", views.scenario_create_view, name="create"),
    path(
        "<slug:slug>/simulator/<int:scenario_id>/action/",
        views.scenario_action_view,
        name="action",
    ),
    path(
        "<slug:slug>/simulator/<int:scenario_id>/status/",
        views.scenario_status_api,
        name="status",
    ),
]
