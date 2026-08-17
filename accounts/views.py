from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from accounts.models import User, LoginActivity, ModelAccess
from registry.models import MLModel
from core.constants import Role, Permission


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:index")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = User.objects.filter(username=username).first()

        if user:
            # Check lockout
            if user.locked_until and user.locked_until > timezone.now():
                remaining_minutes = (
                    int((user.locked_until - timezone.now()).total_seconds() // 60) + 1
                )
                messages.error(
                    request,
                    f"Account is temporarily locked due to multiple failed login attempts. Please try again in {remaining_minutes} minutes.",
                )
                return render(request, "accounts/login.html")

            # Verify password
            authenticated_user = authenticate(
                request, username=username, password=password
            )
            if authenticated_user:
                if not authenticated_user.is_active:
                    messages.error(
                        request, "Account is disabled. Please contact an administrator."
                    )
                    return render(request, "accounts/login.html")

                login(request, authenticated_user)
                next_url = request.GET.get("next") or "dashboard:index"
                return redirect(next_url)
            else:
                # Failed login for existing user -> increment count & lock if >= 5
                user.failed_login_count += 1
                if user.failed_login_count >= 5:
                    user.locked_until = timezone.now() + timedelta(minutes=15)
                    messages.error(
                        request,
                        "Account is temporarily locked due to multiple failed login attempts. Please try again in 15 minutes.",
                    )
                else:
                    # Uniform error message to avoid username enumeration
                    messages.error(request, "Invalid username or password.")
                user.save(update_fields=["failed_login_count", "locked_until"])
                return render(request, "accounts/login.html")
        else:
            # Non-existent user -> trigger failure signal & return identical error message
            authenticate(request, username=username, password=password)
            messages.error(request, "Invalid username or password.")
            return render(request, "accounts/login.html")

    return render(request, "accounts/login.html")


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@login_required
def profile_view(request):
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, "Password updated successfully.")
            return redirect("accounts:profile")
        else:
            messages.error(request, "Please correct the password errors below.")
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, "accounts/profile.html", {"form": form})


@login_required
def user_list_view(request):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Admin role required.")
    users = User.objects.all().order_by("-date_joined")
    return render(request, "accounts/admin_users.html", {"users": users})


@login_required
def user_create_edit_view(request, user_id=None):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Admin role required.")

    target_user = get_object_or_404(User, pk=user_id) if user_id else None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        role = request.POST.get("role", Role.ML_ENGINEER)
        is_active = request.POST.get("is_active") == "on"
        password = request.POST.get("password", "")

        if not target_user:
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already exists.")
                return render(
                    request,
                    "accounts/admin_user_form.html",
                    {"target_user": target_user, "roles": Role.choices},
                )
            target_user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                role=role,
                is_active=is_active,
            )
            messages.success(request, f"User '{username}' created successfully.")
        else:
            target_user.username = username
            target_user.email = email
            target_user.role = role
            target_user.is_active = is_active
            if password:
                target_user.set_password(password)
            target_user.save()
            messages.success(request, f"User '{username}' updated successfully.")

        return redirect("accounts:user_list")

    return render(
        request,
        "accounts/admin_user_form.html",
        {"target_user": target_user, "roles": Role.choices},
    )


@login_required
def access_grants_view(request):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Admin role required.")

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        model_id = request.POST.get("model_id")
        permission = request.POST.get("permission", Permission.VIEW)
        action = request.POST.get("action", "grant")

        target_user = get_object_or_404(User, pk=user_id)
        ml_model = get_object_or_404(MLModel, pk=model_id)

        if action == "revoke":
            ModelAccess.objects.filter(user=target_user, ml_model=ml_model).delete()
            messages.success(
                request,
                f"Access revoked for {target_user.username} on {ml_model.name}.",
            )
        else:
            ModelAccess.objects.update_or_create(
                user=target_user,
                ml_model=ml_model,
                defaults={"permission": permission, "granted_by": request.user},
            )
            messages.success(
                request,
                f"Granted {permission} access to {target_user.username} on {ml_model.name}.",
            )
        return redirect("accounts:access_grants")

    grants = ModelAccess.objects.select_related("user", "ml_model", "granted_by").all()
    users = User.objects.exclude(role=Role.ADMIN)
    models = MLModel.objects.all()

    return render(
        request,
        "accounts/admin_access.html",
        {
            "grants": grants,
            "users": users,
            "models": models,
            "permissions": Permission.choices,
        },
    )


@login_required
def login_activity_view(request):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Admin role required.")

    activities = LoginActivity.objects.select_related("user").all()[:200]
    return render(request, "accounts/admin_activity.html", {"activities": activities})
