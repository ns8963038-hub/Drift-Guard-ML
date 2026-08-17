"""Seed a demo-ready database.

Produces the state the demo script in APP_FLOW.md §8 walks through: three users
of different roles, two models with real artifacts and baselines, deliberately
asymmetric access grants so role-based access control can be *shown* rather than
asserted, a ready drift scenario, and enough monitoring history that the charts
have something to draw.

Usage:
    python scripts/seed_demo.py            # create, skip anything present
    python scripts/seed_demo.py --reset    # delete demo data first
    python scripts/seed_demo.py --runs 40  # how much history to generate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
# The scheduler must not tick while we are seeding — batches would interleave
# with the history being generated here.
os.environ["SCHEDULER_ENABLED"] = "False"
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import ModelAccess, User  # noqa: E402
from alerts.models import Alert, ThresholdProfile  # noqa: E402
from core.constants import Permission, ProblemType, Role, VersionStatus  # noqa: E402
from datasets.services import create_baseline_dataset  # noqa: E402
from monitoring.models import MonitoringRun  # noqa: E402
from monitoring.services import compute_baseline_prediction_distribution  # noqa: E402
from registry.models import MLModel, ModelVersion  # noqa: E402
from simulator import services as sim_services  # noqa: E402
from simulator import transforms  # noqa: E402
from simulator.models import SimulationScenario  # noqa: E402

DATA = ROOT / "data" / "processed"
MANIFEST = ROOT / "artifacts" / "manifest.json"

PASSWORD = "driftguard123"

USERS = [
    ("admin", Role.ADMIN, "Priya (Admin)"),
    ("dsci", Role.DATA_SCIENTIST, "Arun (Data Scientist)"),
    ("mleng", Role.ANALYST, "Sana (Analyst)"),
]

MODELS = {
    "telco_churn": {
        "name": "Customer Churn Model",
        "slug": "customer-churn-model",
        "target": "Churn",
        "positive_class": "Yes",
        "description": "Predicts which subscribers are about to cancel.",
        "drift_numeric": "MonthlyCharges",
        "drift_categorical": "Contract",
    },
    "adult_income": {
        "name": "Income Prediction Model",
        "slug": "income-prediction-model",
        "target": "income",
        "positive_class": ">50K",
        "description": "Predicts whether annual income exceeds $50K.",
        "drift_numeric": "age",
        "drift_categorical": "education",
    },
}


def log(message):
    print(f"  {message}")


def reset():
    log("removing existing demo data")
    MLModel.objects.filter(slug__in=[c["slug"] for c in MODELS.values()]).delete()
    User.objects.filter(username__in=[u[0] for u in USERS]).delete()


def seed_users():
    created = {}
    for username, role, label in USERS:
        user, made = User.objects.get_or_create(
            username=username,
            defaults={"role": role, "email": f"{username}@driftguard.local"},
        )
        if made:
            user.set_password(PASSWORD)
            user.save()
        created[username] = user
        log(f"{'created' if made else 'exists '} {username:<6} {role:<15} {label}")
    return created


def seed_model(key, config, owner, manifest):
    if MLModel.objects.filter(slug=config["slug"]).exists():
        log(f"{config['name']} already exists — skipping")
        return MLModel.objects.get(slug=config["slug"])

    ml_model = MLModel.objects.create(
        name=config["name"],
        slug=config["slug"],
        description=config["description"],
        target_column=config["target"],
        positive_class=config["positive_class"],
        problem_type=ProblemType.BINARY,
        owner=owner,
    )
    # PRD §5.1 — the creator holds MANAGE on what they create.
    ModelAccess.objects.get_or_create(
        user=owner, ml_model=ml_model, defaults={"permission": Permission.MANAGE}
    )

    versions = [m for m in manifest if m["dataset"] == key]
    baseline_path = DATA / key / "baseline.csv"
    created_versions = []

    for entry in versions:
        version = ModelVersion.objects.create(
            ml_model=ml_model,
            version_number=int(entry["version"][1:]),
            label=entry["version"],
            artifact=SimpleUploadedFile(
                Path(entry["artifact"]).name, (ROOT / entry["artifact"]).read_bytes()
            ),
            algorithm_name=entry["algorithm"],
            training_accuracy=entry["training_accuracy"],
            status=VersionStatus.INACTIVE,
            validation_status="PASSED",
            changelog=(
                f"{entry['algorithm']} — accuracy {entry['training_accuracy']:.4f}, "
                f"F1 {entry['training_f1']:.4f}, recall {entry['training_recall']:.4f}"
            ),
            uploaded_by=owner,
        )
        created_versions.append(version)

    # Activate the last version, and hang the baseline off it.
    active = created_versions[-1]
    with open(baseline_path, "rb") as handle:
        create_baseline_dataset(
            ml_model,
            active,
            SimpleUploadedFile("baseline.csv", handle.read()),
            target_column=config["target"],
            user=owner,
        )
    active.status = VersionStatus.ACTIVE
    active.save(update_fields=["status"])
    compute_baseline_prediction_distribution(active)

    ThresholdProfile.objects.get_or_create(ml_model=ml_model)

    log(
        f"created {config['name']}: {len(created_versions)} version(s), "
        f"{active.label} active"
    )
    return ml_model


def seed_scenario(ml_model, key, config, owner):
    if ml_model.scenarios.exists():
        return ml_model.scenarios.first()

    baseline = ml_model.baselines.first()
    plan = transforms.default_scenario(
        config["drift_numeric"], config["drift_categorical"]
    )

    entry = baseline.profile.get("columns", {}).get(config["drift_categorical"], {})
    categories = entry.get("categories", {})
    if categories:
        dominant = max(categories, key=categories.get)
        share = {c: 0.10 / max(len(categories) - 1, 1) for c in categories}
        share[dominant] = 0.90
        plan["phases"][2]["transformations"][2]["target_proportions"] = share

    transforms.validate_drift_plan(plan, baseline.schema)

    with open(DATA / key / "holdout.csv", "rb") as handle:
        holdout = SimpleUploadedFile("holdout.csv", handle.read())

    scenario = SimulationScenario.objects.create(
        ml_model=ml_model,
        name=f"{ml_model.name} — drift demo",
        description=(
            "Batches 0–9 replay clean held-out data. Moderate drift begins at "
            "batch 10, high drift at batch 25."
        ),
        interval_seconds=int(os.getenv("SIMULATOR_DEFAULT_INTERVAL_SECONDS", "30")),
        batch_size=500,
        include_labels=True,
        drift_plan=plan,
        holdout_file=holdout,
        created_by=owner,
    )
    log(f"created scenario for {ml_model.name}")
    return scenario


def generate_history(scenario, count):
    """Run the scenario forward so the charts have something to draw.

    A freshly seeded demo with no runs shows empty charts everywhere, which is
    the worst possible first impression. Generating history here also proves the
    progression works before anyone stands up to present it.
    """
    log(f"generating {count} runs for {scenario.ml_model.name} (this takes a moment)")
    milestones = []
    for _ in range(count):
        run = sim_services.run_one_batch(scenario)
        if run and scenario.next_batch_index - 1 in (0, 10, 25, count - 1):
            milestones.append(
                (
                    scenario.next_batch_index - 1,
                    run.overall_drift_status,
                    run.health_score,
                )
            )
    for index, status, health in milestones:
        log(f"  batch {index:>2}: {status:<9} health {health}")

    _spread_over_time(scenario.ml_model, count)


def _spread_over_time(ml_model, count, hours_apart=6):
    """Backdate the seeded runs so they occupy a plausible stretch of time.

    Seeding runs them in a burst, so all `count` runs land within about a
    second. Every chart's x-axis then reads the same "17 Aug 13:15" `count`
    times over, and "last run 4 hours ago" is identical for all of them —
    on a product whose entire subject is change over time.

    `created_at` is auto_now_add, so it can only be rewritten through a
    queryset update, which bypasses the field's auto behaviour.
    """
    runs = list(
        MonitoringRun.objects.filter(ml_model=ml_model).order_by("created_at", "pk")
    )
    if not runs:
        return
    # The newest run finishes an hour ago, the rest step back from there, so
    # the demo always looks freshly active regardless of when it was seeded.
    end = timezone.now() - timedelta(hours=1)
    stamps = {}
    for offset, run in enumerate(reversed(runs)):
        stamp = end - timedelta(hours=hours_apart * offset)
        stamps[run.pk] = stamp
        MonitoringRun.objects.filter(pk=run.pk).update(
            created_at=stamp, started_at=stamp, completed_at=stamp
        )

    # Alerts carry auto_now_add/auto_now stamps of their own, so they show the
    # seeding burst too. An alert points at the run that last raised it, and it
    # was first seen roughly one occurrence-interval per occurrence earlier.
    earliest = min(stamps.values())
    for alert in Alert.objects.filter(ml_model=ml_model):
        last = stamps.get(alert.run_id, end)
        first = last - timedelta(hours=hours_apart * max(alert.occurrence_count - 1, 0))
        Alert.objects.filter(pk=alert.pk).update(
            last_seen_at=last, first_seen_at=max(first, earliest)
        )

    span = hours_apart * (len(runs) - 1) / 24
    log(f"  spread {len(runs)} runs over {span:.1f} days, newest 1 hour ago")


def seed_access(users, models):
    """Deliberately asymmetric, so RBAC can be demonstrated rather than claimed.

    The Analyst is granted Churn and denied Income. During the demo, opening
    the Income URL as that user returns 404 — access control that can be *shown*,
    not just asserted in a slide.
    """
    churn = models["telco_churn"]
    ModelAccess.objects.get_or_create(
        user=users["mleng"], ml_model=churn, defaults={"permission": Permission.VIEW}
    )
    log("granted mleng VIEW on Customer Churn Model (and nothing on Income)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # Reset is the default. Both README.md and the walkthrough tell the reader
    # to run this script plainly, and the old opt-in --reset meant a second run
    # appended a second set of runs to the first — 32 became 64, the charts grew
    # a duplicate history, and nothing said so.
    parser.add_argument(
        "--keep",
        action="store_true",
        help="add to existing demo data instead of replacing it (rarely wanted)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help=argparse.SUPPRESS,  # accepted for compatibility; now the default
    )
    parser.add_argument("--runs", type=int, default=32, help="history runs to generate")
    args = parser.parse_args()

    if not MANIFEST.exists():
        raise SystemExit(
            "No trained artifacts found.\n"
            "Run: python scripts/prepare_datasets.py && python scripts/train_demo_models.py"
        )

    manifest = json.loads(MANIFEST.read_text())

    print("Seeding DriftGuard demo data\n")
    if args.keep:
        log("keeping existing demo data (--keep)")
    else:
        reset()

    print("Users")
    users = seed_users()

    print("\nModels")
    models = {}
    for key, config in MODELS.items():
        models[key] = seed_model(key, config, users["dsci"], manifest)

    print("\nAccess grants")
    seed_access(users, models)

    print("\nScenarios")
    scenarios = {
        key: seed_scenario(models[key], key, config, users["dsci"])
        for key, config in MODELS.items()
    }

    if args.runs:
        print("\nMonitoring history")
        generate_history(scenarios["telco_churn"], args.runs)

    print("\nDone. Sign in at http://127.0.0.1:8000/ with any of:")
    for username, role, label in USERS:
        print(f"  {username:<6} / {PASSWORD:<16} {role:<15} {label}")
    print(
        "\nThe demo script is in docs/APP_FLOW.md §8. Start the server with:\n"
        "  DJANGO_DEBUG=0 python manage.py runserver --noreload\n"
        "(--noreload matters: the autoreloader would start a second scheduler.)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
