"""Scenario management — S20.

The screen an examiner watches. It has to make three things obvious: what the
scenario is doing right now, which drift phase it has reached, and that a batch
can be forced immediately rather than waiting for the next tick.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.constants import Permission, Role, ScenarioStatus
from core.mixins import model_permission_required, role_required, visible_models
from datasets.services import get_active_baseline
from monitoring.services import IngestionError
from simulator import services, transforms
from simulator.models import SimulationScenario
from simulator.scheduler import next_run_time


@login_required
@role_required(Role.DATA_SCIENTIST)
@model_permission_required(Permission.MANAGE)
def scenario_list_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    scenarios = ml_model.scenarios.all()

    baseline = get_active_baseline(ml_model)
    numeric, categorical = [], []
    if baseline:
        for column, spec in baseline.schema.items():
            if not spec.get("is_feature"):
                continue
            (numeric if spec.get("type") == "NUMERIC" else categorical).append(column)

    return render(
        request,
        "simulator/scenario_list.html",
        {
            "ml_model": ml_model,
            "scenarios": [
                {
                    "scenario": s,
                    "phase": s.phase_description(),
                    "next_run": next_run_time(s),
                }
                for s in scenarios
            ],
            "numeric_columns": numeric,
            "categorical_columns": categorical,
            "has_baseline": baseline is not None,
            "tab": "simulator",
        },
    )


@login_required
@role_required(Role.DATA_SCIENTIST)
@model_permission_required(Permission.MANAGE)
def scenario_create_view(request, slug):
    """Create a scenario, defaulting to the calibrated demo progression."""
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    if request.method != "POST":
        return redirect("simulator:list", slug=slug)

    baseline = get_active_baseline(ml_model)
    if baseline is None:
        messages.error(
            request,
            "Upload a baseline dataset first — a scenario needs a reference to "
            "drift away from.",
        )
        return redirect("simulator:list", slug=slug)

    numeric = request.POST.get("numeric_column") or ""
    categorical = request.POST.get("categorical_column") or ""

    plan = transforms.default_scenario(numeric, categorical)
    if categorical:
        # Fill in the target mix from the baseline's own categories, so the
        # phase-3 shift names values that actually exist in this dataset.
        entry = baseline.profile.get("columns", {}).get(categorical, {})
        categories = list(entry.get("categories", {}))
        if categories:
            dominant = max(entry["categories"], key=entry["categories"].get)
            share = {c: 0.0 for c in categories}
            share[dominant] = 0.90
            remainder = 0.10 / max(len(categories) - 1, 1)
            for c in categories:
                if c != dominant:
                    share[c] = remainder
            plan["phases"][2]["transformations"][2]["target_proportions"] = share

    scenario = SimulationScenario(
        ml_model=ml_model,
        name=request.POST.get("name") or f"{ml_model.name} drift scenario",
        description=request.POST.get("description", ""),
        interval_seconds=int(request.POST.get("interval_seconds", 30)),
        batch_size=int(request.POST.get("batch_size", 500)),
        include_labels=request.POST.get("include_labels") == "on",
        drift_plan=plan,
        holdout_file=request.FILES.get("holdout"),
        created_by=request.user,
    )

    try:
        scenario.clean()
        transforms.validate_drift_plan(plan, baseline.schema)
    except (ValidationError, transforms.DriftPlanError) as exc:
        messages.error(request, str(exc))
        return redirect("simulator:list", slug=slug)

    scenario.save()
    messages.success(
        request,
        "Scenario created. Batches 0–9 are clean, moderate drift begins at "
        "batch 10 and high drift at batch 25.",
    )
    return redirect("simulator:list", slug=slug)


@login_required
@role_required(Role.DATA_SCIENTIST)
@model_permission_required(Permission.MANAGE)
def scenario_action_view(request, slug, scenario_id):
    """Start / pause / resume / stop / run-one-now."""
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    scenario = get_object_or_404(SimulationScenario, pk=scenario_id, ml_model=ml_model)
    action = request.POST.get("action", "")

    try:
        if action in ("start", "resume"):
            services.start(scenario)
            messages.success(
                request,
                f"Running — a batch every {scenario.interval_seconds} seconds, "
                f"starting from batch {scenario.next_batch_index}.",
            )
        elif action == "pause":
            services.pause(scenario)
            messages.info(request, f"Paused at batch {scenario.next_batch_index}.")
        elif action == "stop":
            services.stop(scenario, reset=request.POST.get("reset") == "on")
            messages.info(request, "Stopped.")
        elif action == "run_now":
            # FR-05.5. The reason this exists: nobody waits for a timer during a
            # viva, and a demo that depends on one is a demo that can stall.
            run = services.run_one_batch(scenario)
            if run is None:
                messages.warning(
                    request, "A run is already in progress for this model."
                )
            else:
                messages.success(
                    request,
                    f"Batch {run.data_batch.batch_index} processed — "
                    f"{run.overall_drift_status} drift, health {run.health_score}/100.",
                )
                return redirect("monitoring:run_detail", run_id=run.pk)
        elif action == "delete":
            services.stop(scenario)
            scenario.delete()
            messages.info(request, "Scenario deleted.")
    except IngestionError as exc:
        messages.error(request, str(exc))

    return redirect("simulator:list", slug=slug)


@login_required
@model_permission_required(Permission.VIEW)
def scenario_status_api(request, slug, scenario_id):
    """Polled by the live panel while a scenario runs."""
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    scenario = get_object_or_404(SimulationScenario, pk=scenario_id, ml_model=ml_model)
    latest = ml_model.runs.order_by("-created_at").first()
    upcoming = next_run_time(scenario)

    return JsonResponse(
        {
            "status": scenario.status,
            "running": scenario.status == ScenarioStatus.RUNNING,
            "next_batch_index": scenario.next_batch_index,
            "phase": scenario.phase_description(),
            "last_tick_at": (
                scenario.last_tick_at.isoformat() if scenario.last_tick_at else None
            ),
            "next_run_at": upcoming.isoformat() if upcoming else None,
            "last_error": scenario.last_error,
            "latest_run": (
                {
                    "id": latest.pk,
                    "drift": latest.overall_drift_status,
                    "health": latest.health_score,
                    "band": latest.health_band,
                }
                if latest
                else None
            ),
        }
    )
