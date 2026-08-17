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

    return render(request, "accounts/profile.html", {"form": form, "nav": "profile"})


@login_required
def user_list_view(request):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Admin role required.")
    users = User.objects.all().order_by("-date_joined")
    return render(
        request, "accounts/admin_users.html", {"users": users, "nav": "users"}
    )


def _user_form_context(target_user, values=None):
    """Context for the user form, from one place.

    The error path used to re-render with ``target_user`` — which is None while
    creating — so a rejected submission came back blank.
    """
    if values is None:
        values = {
            "username": target_user.username if target_user else "",
            "email": target_user.email if target_user else "",
            "role": target_user.role if target_user else Role.ANALYST,
            "is_active": target_user.is_active if target_user else True,
        }
    return {
        "target_user": target_user,
        "roles": Role.choices,
        "values": values,
        "nav": "users",
    }


@login_required
def user_create_edit_view(request, user_id=None):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Admin role required.")

    target_user = get_object_or_404(User, pk=user_id) if user_id else None

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        role = request.POST.get("role", Role.ANALYST)
        is_active = request.POST.get("is_active") == "on"
        password = request.POST.get("password", "")

        def reject(message):
            messages.error(request, message)
            return render(
                request,
                "accounts/admin_user_form.html",
                _user_form_context(
                    target_user,
                    {
                        "username": username,
                        "email": email,
                        "role": role,
                        "is_active": is_active,
                    },
                ),
            )

        if not username:
            # create_user() raises ValueError on a blank username, which would
            # surface as a 500 rather than as a message on the form.
            return reject("A username is required.")
        if role not in Role.values:
            return reject("That is not a valid role.")

        # The uniqueness check existed only on the create path. Renaming an
        # existing user onto a taken name reached save() and raised
        # IntegrityError — a 500 on an ordinary typo.
        clash = User.objects.filter(username=username)
        if target_user:
            clash = clash.exclude(pk=target_user.pk)
        if clash.exists():
            return reject(f"The username '{username}' is already taken.")

        # An administrator editing their own account could remove their own
        # admin role or deactivate themselves, locking everyone out of user
        # management with no way back in through the interface.
        editing_self = target_user is not None and target_user.pk == request.user.pk
        if editing_self and role != Role.ADMIN:
            return reject(
                "You cannot remove your own Administrator role. "
                "Ask another administrator to change it."
            )
        if editing_self and not is_active:
            return reject("You cannot deactivate your own account.")

        if not target_user:
            if not password:
                return reject("A password is required for a new user.")
            target_user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                role=role,
                is_active=is_active,
            )
            messages.success(request, f"User '{username}' created.")
        else:
            target_user.username = username
            target_user.email = email
            target_user.role = role
            target_user.is_active = is_active
            if password:
                target_user.set_password(password)
            target_user.save()
            messages.success(request, f"User '{username}' updated.")

        return redirect("accounts:user_list")

    return render(
        request, "accounts/admin_user_form.html", _user_form_context(target_user)
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
            "nav": "access",
        },
    )


@login_required
def login_activity_view(request):
    if request.user.role != Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Admin role required.")

    activities = LoginActivity.objects.select_related("user").all()[:200]
    return render(
        request,
        "accounts/admin_activity.html",
        {"activities": activities, "nav": "activity"},
    )
