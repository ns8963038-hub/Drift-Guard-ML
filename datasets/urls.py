from django.urls import path

from datasets import views

app_name = "datasets"

urlpatterns = [
    path(
        "<slug:slug>/baseline/new/", views.baseline_upload_view, name="baseline_upload"
    ),
    path("<slug:slug>/batches/new/", views.batch_upload_view, name="batch_upload"),
]
