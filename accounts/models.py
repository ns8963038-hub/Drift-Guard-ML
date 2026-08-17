from django.contrib.auth.models import AbstractUser
from django.db import models
from core.constants import Role, Permission, LoginEvent


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ANALYST)
    failed_login_count = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    def is_admin(self):
        return self.role == Role.ADMIN or self.is_superuser

    def is_data_scientist(self):
        return self.role == Role.DATA_SCIENTIST

    def is_analyst(self):
        return self.role == Role.ANALYST


class LoginActivity(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    username_attempted = models.CharField(max_length=150)
    event = models.CharField(max_length=20, choices=LoginEvent.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Login activities"
        ordering = ["-occurred_at"]


class ModelAccess(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="model_accesses"
    )
    ml_model = models.ForeignKey(
        "registry.MLModel", on_delete=models.CASCADE, related_name="access_grants"
    )
    permission = models.CharField(
        max_length=20, choices=Permission.choices, default=Permission.VIEW
    )
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_accesses",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "ml_model")
        verbose_name_plural = "Model accesses"
