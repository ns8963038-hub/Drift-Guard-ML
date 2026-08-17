"""Shared fixtures.

The fully set-up model fixture lives here rather than being imported between
test modules — pytest injects fixtures by name from conftest, and cross-importing
them shadows the definition and trips F811.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed" / "telco_churn"
MANIFEST = ROOT / "artifacts" / "manifest.json"

FIXTURES_PRESENT = MANIFEST.exists() and (DATA / "baseline.csv").exists()


def holdout(n=600, seed=0):
    """A slice of held-out real rows — the same population as the baseline."""
    return (
        pd.read_csv(DATA / "holdout.csv")
        .sample(n, random_state=seed)
        .reset_index(drop=True)
    )


def drifted(n=600, seed=1):
    """Held-out rows with a shifted numeric column and a flipped category mix."""
    baseline = pd.read_csv(DATA / "baseline.csv")
    batch = holdout(n, seed)
    rng = np.random.default_rng(seed)
    batch["MonthlyCharges"] = (
        batch["MonthlyCharges"] + 2.5 * baseline["MonthlyCharges"].std()
    )
    batch["Contract"] = rng.choice(
        ["Month-to-month", "One year", "Two year"], len(batch), p=[0.92, 0.05, 0.03]
    )
    return batch


@pytest.fixture
def churn_model(db, tmp_path, settings):
    """A model with a baseline uploaded and a real artifact activated."""
    if not FIXTURES_PRESENT:
        pytest.skip("run scripts/prepare_datasets.py then scripts/train_demo_models.py")

    from accounts.models import User
    from core.constants import ProblemType, Role, VersionStatus
    from datasets.services import create_baseline_dataset
    from monitoring.services import compute_baseline_prediction_distribution
    from registry.models import MLModel, ModelVersion

    settings.MEDIA_ROOT = str(tmp_path)

    owner = User.objects.create_user(
        username="ds", password="p", role=Role.DATA_SCIENTIST
    )
    ml_model = MLModel.objects.create(
        name="Customer Churn Model",
        slug="customer-churn-model",
        target_column="Churn",
        positive_class="Yes",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )

    entry = next(
        m
        for m in json.loads(MANIFEST.read_text())
        if m["dataset"] == "telco_churn" and m["version"] == "V2"
    )
    version = ModelVersion.objects.create(
        ml_model=ml_model,
        version_number=1,
        label="V1",
        artifact=SimpleUploadedFile(
            "model.joblib", (ROOT / entry["artifact"]).read_bytes()
        ),
        status=VersionStatus.ACTIVE,
        training_accuracy=entry["training_accuracy"],
    )

    with open(DATA / "baseline.csv", "rb") as handle:
        create_baseline_dataset(
            ml_model,
            version,
            SimpleUploadedFile("baseline.csv", handle.read()),
            target_column="Churn",
            user=owner,
        )

    compute_baseline_prediction_distribution(version)
    version.refresh_from_db()
    return ml_model, version, owner
