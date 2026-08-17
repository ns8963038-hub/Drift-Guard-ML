"""Simulator lifecycle and scheduler tests — PRD FR-05.

The acceptance criterion that matters is the unattended progression: a scenario
must move NONE -> MODERATE -> HIGH on its own, survive a restart, and never let
a failure kill the scheduler.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.constants import BatchSource, DriftStatus, ScenarioStatus
from simulator import services, transforms
from simulator.models import SimulationScenario
from tests.conftest import DATA, FIXTURES_PRESENT

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not FIXTURES_PRESENT, reason="demo fixtures not built"),
]


@pytest.fixture
def scenario(churn_model):
    ml_model, _, owner = churn_model
    plan = transforms.default_scenario("MonthlyCharges", "Contract")
    plan["phases"][2]["transformations"][2]["target_proportions"] = {
        "Month-to-month": 0.90,
        "One year": 0.07,
        "Two year": 0.03,
    }
    with open(DATA / "holdout.csv", "rb") as handle:
        holdout = SimpleUploadedFile("holdout.csv", handle.read())

    return SimulationScenario.objects.create(
        ml_model=ml_model,
        name="Demo",
        interval_seconds=10,
        batch_size=400,
        drift_plan=plan,
        holdout_file=holdout,
        created_by=owner,
    )


# ──────────────────────────────────────────────────────────────────────
# The unattended progression — FR-05 acceptance criterion
# ──────────────────────────────────────────────────────────────────────


def test_scenario_progresses_from_clean_to_high_drift(scenario):
    """The centrepiece of the demo, driven entirely by the scenario position."""
    statuses = {}
    for index in (2, 15, 30):
        scenario.next_batch_index = index
        scenario.save(update_fields=["next_batch_index"])
        run = services.run_one_batch(scenario, advance=False)
        statuses[index] = run.overall_drift_status

    assert statuses[2] == DriftStatus.NONE, "the clean phase must look clean"
    assert statuses[15] == DriftStatus.MODERATE, "phase 2 must be amber, not red"
    assert statuses[30] == DriftStatus.HIGH, "phase 3 must be unambiguous"


def test_each_batch_is_recorded_as_simulator_sourced(scenario):
    run = services.run_one_batch(scenario)
    assert run.data_batch.source == BatchSource.SIMULATOR
    assert run.data_batch.batch_index == 0
    assert run.trigger_source == "SCHEDULED"


def test_position_advances_and_persists(scenario):
    """FR-05.4 — a restart resumes rather than replaying from zero."""
    services.run_one_batch(scenario)
    services.run_one_batch(scenario)

    scenario.refresh_from_db()
    assert scenario.next_batch_index == 2
    assert scenario.last_tick_at is not None


def test_scenario_can_withhold_labels(scenario):
    """Simulating the realistic case where ground truth has not arrived."""
    scenario.include_labels = False
    scenario.save(update_fields=["include_labels"])

    run = services.run_one_batch(scenario)
    assert run.labels_available is False
    assert run.performance.accuracy is None
    assert run.feature_results.count() == 19


# ──────────────────────────────────────────────────────────────────────
# Lifecycle
# ──────────────────────────────────────────────────────────────────────


def test_pause_keeps_position_and_stop_can_reset(scenario):
    services.run_one_batch(scenario)
    services.pause(scenario)
    scenario.refresh_from_db()

    assert scenario.status == ScenarioStatus.PAUSED
    assert scenario.next_batch_index == 1, "pausing must not lose the story so far"

    services.stop(scenario, reset=True)
    scenario.refresh_from_db()
    assert scenario.status == ScenarioStatus.STOPPED
    assert scenario.next_batch_index == 0


def test_tick_on_a_stopped_scenario_does_nothing(scenario):
    assert services.tick(scenario.pk) is None
    assert scenario.ml_model.runs.count() == 0


def test_tick_never_raises_into_the_scheduler(scenario):
    """PRD NFR-9 — an exception here would silently kill the job.

    A scenario with no holdout data cannot produce a batch. The failure must be
    recorded on the scenario and swallowed, not propagated to the thread.
    """
    scenario.status = ScenarioStatus.RUNNING
    scenario.holdout_file = None
    scenario.save(update_fields=["status", "holdout_file"])

    assert services.tick(scenario.pk) is None

    scenario.refresh_from_db()
    assert "holdout" in scenario.last_error.lower()
    assert scenario.status == ScenarioStatus.RUNNING, "one failure is not a stop"


def test_tick_for_a_deleted_scenario_is_harmless(scenario):
    scenario_id = scenario.pk
    scenario.delete()
    assert services.tick(scenario_id) is None


# ──────────────────────────────────────────────────────────────────────
# The screen
# ──────────────────────────────────────────────────────────────────────


def test_scenario_screen_renders(client, scenario):
    client.force_login(scenario.created_by)
    response = client.get(reverse("simulator:list", args=[scenario.ml_model.slug]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Demo" in body
    assert "Run one batch now" in body
    assert "production setting: hourly" in body


def test_run_now_produces_a_batch_immediately(client, scenario):
    """FR-05.5 — nobody waits for a timer during a viva."""
    client.force_login(scenario.created_by)
    response = client.post(
        reverse("simulator:action", args=[scenario.ml_model.slug, scenario.pk]),
        {"action": "run_now"},
        follow=True,
    )

    assert response.status_code == 200
    assert scenario.ml_model.runs.count() == 1


def test_status_endpoint_reports_live_position(client, scenario):
    client.force_login(scenario.created_by)
    services.run_one_batch(scenario)

    payload = client.get(
        reverse("simulator:status", args=[scenario.ml_model.slug, scenario.pk])
    ).json()

    assert payload["next_batch_index"] == 1
    assert payload["latest_run"]["id"]
    assert payload["phase"]


def test_analyst_cannot_manage_scenarios(client, scenario):
    """PRD §5.2 — configuring the feed is a Data Scientist decision."""
    from accounts.models import ModelAccess, User
    from core.constants import Permission, Role
    from django.core.exceptions import PermissionDenied

    engineer = User.objects.create_user(username="eng", password="p", role=Role.ANALYST)
    ModelAccess.objects.create(
        user=engineer, ml_model=scenario.ml_model, permission=Permission.VIEW
    )
    client.force_login(engineer)

    try:
        response = client.get(reverse("simulator:list", args=[scenario.ml_model.slug]))
        assert response.status_code in (403, 404)
    except PermissionDenied:
        pass


# ──────────────────────────────────────────────────────────────────────
# The autoreload guard — regression test
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv,run_main,should_skip,why",
    [
        (["manage.py", "runserver"], None, True, "reloader parent"),
        (["manage.py", "runserver"], "true", False, "reloader child"),
        (["manage.py", "runserver", "--noreload"], None, False, "single process"),
        (["manage.py", "runserver", "--noreload"], "true", False, "single process"),
        (["gunicorn", "config.wsgi"], None, False, "gunicorn worker"),
        (["manage.py", "shell"], None, False, "management command"),
    ],
)
def test_scheduler_starts_in_exactly_the_right_processes(
    monkeypatch, argv, run_main, should_skip, why
):
    """Regression: `runserver --noreload` silently disabled the scheduler.

    The original guard was `RUN_MAIN != "true"`, which is true in the reloader
    parent — but also true under `--noreload` and under gunicorn, neither of
    which set RUN_MAIN. So the scheduler never started in exactly the way the
    README tells people to run the project, and nothing indicated it: the site
    served normally, scenarios showed as RUNNING, and no batch ever arrived.

    The guard must skip in one case only: the reloader's supervising process.
    """
    import sys

    from simulator import scheduler

    monkeypatch.setattr(sys, "argv", argv)
    if run_main is None:
        monkeypatch.delenv("RUN_MAIN", raising=False)
    else:
        monkeypatch.setenv("RUN_MAIN", run_main)

    assert scheduler._is_autoreload_parent() is should_skip, why
