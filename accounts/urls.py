from django.urls import path
from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("admin-panel/users/", views.user_list_view, name="user_list"),
    path("admin-panel/users/new/", views.user_create_edit_view, name="user_create"),
    path(
        "admin-panel/users/<int:user_id>/",
        views.user_create_edit_view,
        name="user_edit",
    ),
    path("admin-panel/access/", views.access_grants_view, name="access_grants"),
    path("admin-panel/activity/", views.login_activity_view, name="login_activity"),
]
