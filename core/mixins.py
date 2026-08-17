from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from core.constants import Role, Permission


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
