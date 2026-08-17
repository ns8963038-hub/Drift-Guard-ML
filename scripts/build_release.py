"""Build the self-contained DriftGuard.zip that ships to the client.

The first bundle was assembled by hand, which is a poor way to produce the one
artifact anybody outside this repository actually runs: there was no record of
what went into it, and no way to tell whether a given zip matched a given
commit. This script is that record.

What goes in is everything needed to run with no internet access and no build
step — the source, the trained artifacts, the prepared baseline data, the media
tree those artifacts live in, and a seeded database with real monitoring history.

What stays out is anything that is generated, secret, or merely large: the
virtualenv, caches, logs, `.git`, `.env`, and the raw dataset downloads (the
processed baselines are what the platform reads).

    python scripts/build_release.py            # -> dist/DriftGuard.zip
    python scripts/build_release.py --verify   # also extract and smoke-test it
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUNDLE = DIST / "DriftGuard.zip"

# The source comes from `git ls-files`, not from a list maintained by hand.
# A hand-written list drifts the moment an app is added: the first attempt at
# this script omitted `apiv1`, which is in INSTALLED_APPS, so the extracted
# bundle could not start at all.
#
# These are the generated things git deliberately ignores but the bundle needs,
# because the whole point is that the client runs it without building anything.
INCLUDE_GENERATED = [
    "artifacts",  # trained .joblib files
    "media",  # the artifact/baseline/batch tree the app reads
    "data/processed",  # prepared baseline CSVs
]

INCLUDE_GENERATED_FILES = ["db.sqlite3"]

# Tracked files that must never travel: secrets, and anything that only makes
# sense inside this repository.
EXCLUDE_TRACKED = {".gitignore", ".github"}

EXCLUDE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".DS_Store",
    "node_modules",
    ".git",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log"}

START_HERE = """DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection
=================================================================

Everything here is pre-built. The datasets are prepared, the models are
trained, and the database already holds monitoring history, so this runs with
no internet connection and nothing to generate.

1. Python 3.11 specifically
---------------------------
Django 5.0 does not support Python 3.12 or newer, and recent macOS ships 3.14
by default. Check with:

    python3.11 --version

2. Set up and run
-----------------
    python3.11 -m venv .venv
    source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
    pip install -r requirements.txt
    DJANGO_DEBUG=0 python manage.py runserver --noreload

On Windows, set the variable first:

    set DJANGO_DEBUG=0
    python manage.py runserver --noreload

Then open http://127.0.0.1:8000/

Both flags matter:

  --noreload      Without it Django runs two processes, and the background
                  scheduler would deliver every simulated batch twice.

  DJANGO_DEBUG=0  With DEBUG on, Django replaces this project's own 403 and
                  404 pages with its developer pages — and the debug 404 lists
                  every URL in the project, which is exactly what the access
                  control demonstration claims a 404 does not reveal.

3. Sign in
----------
    admin  / driftguard123    Administrator
    dsci   / driftguard123    Data Scientist
    mleng  / driftguard123    Analyst

The three roles see genuinely different screens. The Analyst is granted the
Churn model and denied the Income model on purpose, so access control can be
shown rather than asserted.

4. Where to go next
-------------------
    docs/WALKTHROUGH.md     A guided tour that doubles as a test pass.
    docs/PRD.md             What it does and why.
    docs/TRD.md             How it is built.

5. Starting over
----------------
To rebuild the demo data from scratch at any point:

    python scripts/seed_demo.py

That replaces the demo users, models and history. Stop the server first — the
database is in use while it runs.
"""


def log(message: str) -> None:
    print(f"  {message}")


def skip(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
        return True
    return any(part in EXCLUDE_NAMES for part in path.parts)


def tracked_files() -> list[str]:
    """Everything git tracks — the project's own definition of its source."""
    output = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return [line for line in output.splitlines() if line]


def collect() -> list[tuple[Path, str]]:
    """Every (source, archive-name) pair that belongs in the bundle."""
    entries: list[tuple[Path, str]] = []
    missing: list[str] = []
    seen: set[str] = set()

    def add(path: Path, name: str) -> None:
        if name not in seen and path.is_file() and not skip(path):
            seen.add(name)
            entries.append((path, name))

    for name in tracked_files():
        if name in EXCLUDE_TRACKED or name.split("/", 1)[0] in EXCLUDE_TRACKED:
            continue
        add(ROOT / name, name)

    for name in INCLUDE_GENERATED_FILES:
        source = ROOT / name
        if source.exists():
            add(source, name)
        else:
            missing.append(name)

    for directory in INCLUDE_GENERATED:
        base = ROOT / directory
        if not base.exists():
            missing.append(directory + "/")
            continue
        for path in sorted(base.rglob("*")):
            add(path, str(path.relative_to(ROOT)))

    # A bundle that cannot start is worse than none, so check the apps the
    # settings actually declare are all present rather than trusting the copy.
    for app in local_apps():
        if not (ROOT / app / "__init__.py").exists():
            missing.append(f"{app}/ (declared in INSTALLED_APPS)")
        elif f"{app}/__init__.py" not in seen:
            missing.append(f"{app}/ (present but not packaged)")

    if missing:
        raise SystemExit(
            "Cannot build a runnable bundle — these are missing:\n  "
            + "\n  ".join(missing)
            + "\n\nRun, in order:\n"
            "  python scripts/prepare_datasets.py\n"
            "  python scripts/train_demo_models.py\n"
            "  python scripts/seed_demo.py"
        )
    return entries


def local_apps() -> list[str]:
    """The project's own apps, read from the settings rather than guessed."""
    text = (ROOT / "config" / "settings" / "base.py").read_text()
    block = text[
        text.index("INSTALLED_APPS") : text.index("]", text.index("INSTALLED_APPS"))
    ]
    return [
        line.strip().strip('",')
        for line in block.splitlines()
        if line.strip().startswith('"') and not line.strip().startswith('"django.')
    ]


def commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build() -> Path:
    DIST.mkdir(exist_ok=True)
    if BUNDLE.exists():
        BUNDLE.unlink()

    entries = collect()
    revision = commit()

    with zipfile.ZipFile(BUNDLE, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, name in entries:
            archive.write(source, f"DriftGuard/{name}")
        archive.writestr("DriftGuard/START_HERE.txt", START_HERE)
        archive.writestr(
            "DriftGuard/BUILD.txt",
            f"Built from commit {revision}\n" f"{len(entries) + 2} files\n",
        )

    size_mb = BUNDLE.stat().st_size / 1_000_000
    log(f"{len(entries) + 2} files, {size_mb:.1f} MB, from commit {revision}")
    return BUNDLE


def verify() -> None:
    """Extract into a clean directory and prove it actually runs.

    A bundle that unpacks but cannot start is worse than no bundle, because the
    failure lands on the client rather than here.
    """
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        with zipfile.ZipFile(BUNDLE) as archive:
            archive.extractall(target)
        extracted = target / "DriftGuard"

        for required in ("manage.py", "db.sqlite3", "START_HERE.txt", "docs/PRD.md"):
            if not (extracted / required).exists():
                raise SystemExit(f"Bundle is missing {required}")
        log("structure looks right")

        artifacts = list((extracted / "media").rglob("*.joblib"))
        if not artifacts:
            raise SystemExit("No model artifacts in media/ — nothing could score")
        log(f"{len(artifacts)} model artifact(s) present")

        # Run Django's own checks against the extracted copy, using this
        # interpreter. It proves the settings, URLs and templates all load.
        env = {
            **os.environ,
            "DJANGO_DEBUG": "0",
            "SCHEDULER_ENABLED": "False",
            "PYTHONPATH": str(extracted),
        }
        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=extracted,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit(
                "The extracted bundle fails Django's checks:\n" + result.stderr
            )
        log("django check passes on the extracted copy")

        # And prove the seeded database is really populated.
        script = (
            "import django, os;"
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.dev');"
            "django.setup();"
            "from monitoring.models import MonitoringRun;"
            "from accounts.models import User;"
            "from registry.models import MLModel;"
            "print(MonitoringRun.objects.count(), User.objects.count(), MLModel.objects.count())"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=extracted,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit("Cannot read the bundled database:\n" + result.stderr)
        runs, users, models = result.stdout.strip().split()[-3:]
        if int(runs) == 0 or int(users) < 3 or int(models) < 2:
            raise SystemExit(
                f"Bundled database looks unseeded: {runs} runs, {users} users, "
                f"{models} models"
            )
        log(f"database holds {runs} runs, {users} users, {models} models")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true", help="extract the bundle and smoke-test it"
    )
    args = parser.parse_args()

    print("Building DriftGuard.zip\n")
    build()

    if args.verify:
        print("\nVerifying from a clean extract")
        verify()

    print(f"\nDone: {BUNDLE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
