from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from core.constants import Role, Permission


def role_required(*allowed_roles):
    """Function-view equivalent of RoleRequiredMixin.

    Most views in this project are function-based, so the class mixins below
    could not be applied to them. Without this, `@login_required` was the only
    gate on `registry/` and `alerts/` — which authenticates the user but
    authorises nothing, and let an ML Engineer create models and reach the
    version upload form in violation of PRD §5.2.

    Admin and superusers always pass.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                raise PermissionDenied("Authentication required.")
            if user.role == Role.ADMIN or user.is_superuser:
                return view(request, *args, **kwargs)
            if user.role not in allowed_roles:
                raise PermissionDenied("Your role does not permit this action.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def model_permission_required(required_permission=Permission.VIEW):
    """Function-view equivalent of ModelAccessRequiredMixin.

    Resolves the model from the ``slug`` URL kwarg and checks the caller's grant.
    A missing model and a denied model raise the same error, so probing URLs
    reveals nothing about what exists (PRD FR-01.7).
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                raise PermissionDenied("Authentication required.")
            if user.role == Role.ADMIN or user.is_superuser:
                return view(request, *args, **kwargs)

            slug = kwargs.get("slug") or kwargs.get("model_slug")
            if not slug:
                return view(request, *args, **kwargs)

            from registry.models import MLModel

            ml_model = MLModel.objects.filter(slug=slug).first()
            if ml_model is None:
                raise PermissionDenied("Model not found or access denied.")

            if ml_model.owner == user:
                return view(request, *args, **kwargs)

            from accounts.models import ModelAccess

            grant = ModelAccess.objects.filter(user=user, ml_model=ml_model).first()
            if grant is None:
                raise PermissionDenied("Model not found or access denied.")
            if (
                required_permission == Permission.MANAGE
                and grant.permission != Permission.MANAGE
            ):
                raise PermissionDenied("You require MANAGE permission for this model.")

            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def visible_models(user):
    from registry.models import MLModel

    if not user.is_authenticated:
        return MLModel.objects.none()
    if user.role == Role.ADMIN or user.is_superuser:
        return MLModel.objects.all()
    # Return models owned by user OR explicitly granted to user via ModelAccess
    return MLModel.objects.filter(
        Q(owner=user) | Q(access_grants__user=user)
    ).distinct()


class RoleRequiredMixin(AccessMixin):
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if (
            request.user.role not in self.allowed_roles
            and not request.user.is_superuser
        ):
            raise PermissionDenied("You do not have permission to perform this action.")
        return super().dispatch(request, *args, **kwargs)


class ModelAccessRequiredMixin(AccessMixin):
    required_permission = Permission.VIEW

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Superuser / Admin always bypass
        if request.user.role == Role.ADMIN or request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)

        model_slug = kwargs.get("slug") or kwargs.get("model_slug")
        if not model_slug:
            return super().dispatch(request, *args, **kwargs)

        from registry.models import MLModel

        try:
            ml_model = MLModel.objects.get(slug=model_slug)
        except MLModel.DoesNotExist:
            raise PermissionDenied("Model not found or access denied.")

        if ml_model.owner == request.user:
            return super().dispatch(request, *args, **kwargs)

        from accounts.models import ModelAccess

        grant = ModelAccess.objects.filter(user=request.user, ml_model=ml_model).first()
        if not grant:
            raise PermissionDenied("Model not found or access denied.")

        if (
            self.required_permission == Permission.MANAGE
            and grant.permission != Permission.MANAGE
        ):
            raise PermissionDenied("You require MANAGE permission for this model.")

        return super().dispatch(request, *args, **kwargs)
