"""Rename the ML_ENGINEER role to ANALYST.

The client's college synopsis (§1) names the three roles as administrators,
data scientists and analysts. The role's permissions and behaviour are
unchanged — only the label the document uses.
"""

from django.db import migrations, models


def to_analyst(apps, schema_editor):
    apps.get_model("accounts", "User").objects.filter(role="ML_ENGINEER").update(
        role="ANALYST"
    )


def to_ml_engineer(apps, schema_editor):
    apps.get_model("accounts", "User").objects.filter(role="ANALYST").update(
        role="ML_ENGINEER"
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_initial")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("ADMIN", "Admin"),
                    ("DATA_SCIENTIST", "Data Scientist"),
                    ("ANALYST", "Analyst"),
                ],
                default="ANALYST",
                max_length=20,
            ),
        ),
        migrations.RunPython(to_analyst, to_ml_engineer),
    ]
