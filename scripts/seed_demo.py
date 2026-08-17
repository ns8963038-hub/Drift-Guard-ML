#!/usr/bin/env python
import os
import sys
import django

# Set up Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from accounts.models import User, ModelAccess  # noqa: E402
from registry.models import MLModel  # noqa: E402
from alerts.models import ThresholdProfile  # noqa: E402
from core.constants import Role, Permission, ProblemType  # noqa: E402


def seed_demo():
    print("🌱 Seeding DriftGuard demo environment...")

    # 1. Create Users for all three roles
    admin, _ = User.objects.get_or_create(
        username="admin",
        defaults={
            "email": "admin@driftguard.local",
            "role": Role.ADMIN,
            "is_superuser": True,
            "is_staff": True,
        },
    )
    admin.set_password("adminpassword123")
    admin.save()

    ds, _ = User.objects.get_or_create(
        username="datascientist",
        defaults={"email": "ds@driftguard.local", "role": Role.DATA_SCIENTIST},
    )
    ds.set_password("dspassword123")
    ds.save()

    mle, _ = User.objects.get_or_create(
        username="mlengineer",
        defaults={"email": "mle@driftguard.local", "role": Role.ML_ENGINEER},
    )
    mle.set_password("mlpassword123")
    mle.save()

    print("  ✓ Created users: admin, datascientist, mlengineer")

    # 2. Create Models
    m1, _ = MLModel.objects.get_or_create(
        slug="telco-customer-churn",
        defaults={
            "name": "Telco Customer Churn",
            "description": "Predicts customer subscription churn probability.",
            "target_column": "Churn",
            "positive_class": "Yes",
            "problem_type": ProblemType.BINARY,
            "owner": mle,
        },
    )

    m2, _ = MLModel.objects.get_or_create(
        slug="adult-census-income",
        defaults={
            "name": "Adult Census Income",
            "description": "Classifies individual income above or below $50K.",
            "target_column": "income",
            "positive_class": ">50K",
            "problem_type": ProblemType.BINARY,
            "owner": ds,
        },
    )

    print("  ✓ Created ML models: Telco Customer Churn, Adult Census Income")

    # 3. Model Access Grants
    ModelAccess.objects.get_or_create(
        user=mle, ml_model=m1, defaults={"permission": Permission.MANAGE}
    )
    ModelAccess.objects.get_or_create(
        user=ds, ml_model=m1, defaults={"permission": Permission.VIEW}
    )
    ModelAccess.objects.get_or_create(
        user=ds, ml_model=m2, defaults={"permission": Permission.MANAGE}
    )
    ModelAccess.objects.get_or_create(
        user=mle, ml_model=m2, defaults={"permission": Permission.VIEW}
    )

    print("  ✓ Configured role access grants")

    # 4. Threshold Profiles
    ThresholdProfile.objects.get_or_create(
        ml_model=m1,
        defaults={"ks_p_value_threshold": 0.05, "psi_threshold": 0.2},
    )
    ThresholdProfile.objects.get_or_create(
        ml_model=m2,
        defaults={"ks_p_value_threshold": 0.01, "psi_threshold": 0.15},
    )

    print("  ✓ Created threshold profiles")
    print("✅ Demo environment seeded successfully!")


if __name__ == "__main__":
    seed_demo()
