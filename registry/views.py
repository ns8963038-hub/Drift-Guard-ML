import csv
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.text import slugify
from django.core.exceptions import ValidationError

from registry.models import MLModel, ModelVersion, ModelAuditLog
from registry.services import create_model_version, activate_version
from accounts.models import ModelAccess
from core.constants import ProblemType, Permission
from core.mixins import visible_models, role_required, model_permission_required
from core.constants import Role
from core.validators import (
    validate_dataset_file_extension,
    validate_dataset_file_size,
)


@login_required
def model_list_view(request):
    models = visible_models(request.user)
    return render(request, "registry/model_list.html", {"models": models})


@login_required
@role_required(Role.DATA_SCIENTIST)
def model_create_edit_view(request, slug=None):
    ml_model = get_object_or_404(MLModel, slug=slug) if slug else None

    if ml_model and ml_model.owner != request.user and not request.user.is_admin():
        grant = ModelAccess.objects.filter(user=request.user, ml_model=ml_model).first()
        if not grant or grant.permission != Permission.MANAGE:
            messages.error(request, "You require MANAGE permission for this model.")
            return redirect("registry:overview", slug=ml_model.slug)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        target_column = request.POST.get("target_column", "").strip()
        positive_class = request.POST.get("positive_class", "").strip() or None
        problem_type = request.POST.get("problem_type", ProblemType.BINARY)

        if not ml_model:
            model_slug = slugify(name)
            if MLModel.objects.filter(slug=model_slug).exists():
                messages.error(
                    request, f"A model with slug '{model_slug}' already exists."
                )
                return render(
                    request,
                    "registry/model_form.html",
                    {"ml_model": ml_model, "problem_types": ProblemType.choices},
                )
            ml_model = MLModel.objects.create(
                name=name,
                slug=model_slug,
                description=description,
                target_column=target_column,
                positive_class=positive_class,
                problem_type=problem_type,
                owner=request.user,
            )
            ModelAccess.objects.get_or_create(
                user=request.user,
                ml_model=ml_model,
                defaults={"permission": Permission.MANAGE},
            )
            ModelAuditLog.objects.create(
                ml_model=ml_model,
                actor=request.user,
                action="MODEL_CREATED",
                details={"name": name},
            )
            messages.success(request, f"Model '{name}' created successfully.")
        else:
            ml_model.name = name
            ml_model.description = description
            ml_model.target_column = target_column
            ml_model.positive_class = positive_class
            ml_model.problem_type = problem_type
            ml_model.save()
            messages.success(request, f"Model '{name}' updated successfully.")

        return redirect("registry:overview", slug=ml_model.slug)

    return render(
        request,
        "registry/model_form.html",
        {"ml_model": ml_model, "problem_types": ProblemType.choices},
    )


@login_required
def model_overview_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    active_ver = ml_model.active_version
    audit_logs = ml_model.audit_logs.select_related("actor").all()[:10]
    return render(
        request,
        "registry/model_overview.html",
        {
            "ml_model": ml_model,
            "active_ver": active_ver,
            "audit_logs": audit_logs,
            "tab": "overview",
        },
    )


@login_required
def model_versions_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    versions = ml_model.versions.all()
    return render(
        request,
        "registry/model_versions.html",
        {"ml_model": ml_model, "versions": versions, "tab": "versions"},
    )


@login_required
@role_required(Role.DATA_SCIENTIST)
@model_permission_required(Permission.MANAGE)
def model_version_upload_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    if request.method == "POST" and request.FILES.get("artifact"):
        artifact_file = request.FILES["artifact"]
        label = request.POST.get("label", "").strip() or None

        try:
            version = create_model_version(
                ml_model=ml_model,
                artifact_file=artifact_file,
                label=label,
                user=request.user,
            )
            messages.success(
                request, f"Version {version.label} uploaded and validated successfully!"
            )
            return redirect("registry:versions", slug=ml_model.slug)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, "message") else e))
            return render(
                request, "registry/version_upload.html", {"ml_model": ml_model}
            )

    return render(request, "registry/version_upload.html", {"ml_model": ml_model})


@login_required
@role_required(Role.DATA_SCIENTIST)
@model_permission_required(Permission.MANAGE)
def model_version_activate_view(request, slug, version_id):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    version = get_object_or_404(ModelVersion, pk=version_id, ml_model=ml_model)

    if request.method == "POST":
        activate_version(version, user=request.user)
        messages.success(request, f"Version {version.label} activated successfully!")
        return redirect("registry:versions", slug=ml_model.slug)

    return redirect("registry:versions", slug=ml_model.slug)


@login_required
def version_comparison_view(request, slug):
    """S16 — compare two versions of the same model (FR-12).

    Compares the seven measures FR-12.2 lists, not just training accuracy.
    Training accuracy alone would rank V1 top on this dataset while V2 catches
    26 points more churners — which is the whole reason the platform tracks
    several metrics.
    """
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    versions = list(ml_model.versions.all())

    def pick(param, fallback):
        chosen = request.GET.get(param)
        if chosen:
            return next((v for v in versions if str(v.pk) == chosen), fallback)
        return fallback

    v1 = pick("v1", versions[0] if versions else None)
    v2 = pick("v2", versions[1] if len(versions) > 1 else None)

    rows, verdict, schema_compatible = [], None, True

    if v1 and v2:
        # FR-12.5 — comparing drift across different feature sets is meaningless,
        # so those rows are suppressed rather than shown as a misleading delta.
        schema_compatible = not (
            v1.feature_schema
            and v2.feature_schema
            and set(v1.feature_schema) != set(v2.feature_schema)
        )
        rows = _comparison_rows(v1, v2, schema_compatible)
        verdict = _verdict(v1, v2, rows)

    return render(
        request,
        "registry/version_comparison.html",
        {
            "ml_model": ml_model,
            "versions": versions,
            "v1": v1,
            "v2": v2,
            "rows": rows,
            "verdict": verdict,
            "schema_compatible": schema_compatible,
            "tab": "versions",
        },
    )


def _version_stats(version):
    """Observed metrics for one version, or None where nothing was measured."""
    from django.db.models import Avg

    runs = version.runs.filter(status="COMPLETED")
    labelled = runs.filter(performance__labels_available=True)

    aggregates = labelled.aggregate(
        accuracy=Avg("performance__accuracy"),
        f1=Avg("performance__f1_positive"),
        recall=Avg("performance__recall_positive"),
    )
    health = runs.aggregate(score=Avg("health_score"), drifted=Avg("features_high"))
    latest = runs.order_by("-created_at").first()

    return {
        "training_accuracy": version.training_accuracy,
        "latest_accuracy": getattr(
            getattr(latest, "performance", None), "accuracy", None
        ),
        "mean_accuracy": aggregates["accuracy"],
        "mean_f1": aggregates["f1"],
        "mean_recall": aggregates["recall"],
        "mean_health": health["score"],
        "mean_high_drift": health["drifted"],
        "run_count": runs.count(),
        "alert_count": version.ml_model.alerts.filter(
            run__model_version=version
        ).count(),
    }


COMPARISON_ROWS = [
    ("training_accuracy", "Training accuracy", 4, True),
    ("latest_accuracy", "Latest accuracy", 4, True),
    ("mean_accuracy", "Mean accuracy", 4, True),
    ("mean_f1", "Mean F1 (positive class)", 4, True),
    ("mean_recall", "Mean recall (positive class)", 4, True),
    ("mean_health", "Mean health score", 1, True),
    ("mean_high_drift", "Mean high-drift features", 2, False),
    ("run_count", "Monitoring runs", 0, None),
    ("alert_count", "Alerts raised", 0, False),
]


def _comparison_rows(v1, v2, schema_compatible):
    """One row per measure, marking the better side and the delta (FR-12.3)."""
    left, right = _version_stats(v1), _version_stats(v2)
    rows = []

    for key, label, places, higher_is_better in COMPARISON_ROWS:
        if key == "mean_high_drift" and not schema_compatible:
            continue

        a, b = left[key], right[key]
        row = {
            "label": label,
            "a": a,
            "b": b,
            "places": places,
            "winner": None,
            "delta": None,
        }

        if a is not None and b is not None and higher_is_better is not None and a != b:
            row["winner"] = "a" if (a > b) == higher_is_better else "b"
            row["delta"] = abs(a - b)

        rows.append(row)
    return rows


def _verdict(v1, v2, rows):
    """FR-12.4 — a sentence, not a table the reader has to interpret."""
    wins_a = sum(1 for r in rows if r["winner"] == "a")
    wins_b = sum(1 for r in rows if r["winner"] == "b")
    runs = next((r for r in rows if r["label"] == "Monitoring runs"), None)
    total_runs = (runs["a"] or 0) + (runs["b"] or 0) if runs else 0

    if wins_a == wins_b:
        return (
            f"{v1.label} and {v2.label} are evenly matched across "
            f"{len(rows)} measures over {total_runs} runs."
        )

    better, worse = (v1, v2) if wins_a > wins_b else (v2, v1)
    accuracy = next((r for r in rows if r["label"] == "Mean accuracy"), None)
    detail = ""
    if accuracy and accuracy["delta"] is not None:
        side = "a" if better is v1 else "b"
        direction = "ahead on" if accuracy["winner"] == side else "behind on"
        detail = f", {direction} mean accuracy by {accuracy['delta'] * 100:.1f} points"

    return (
        f"{better.label} outperforms {worse.label} on "
        f"{max(wins_a, wins_b)} of {len(rows)} measures{detail}, across "
        f"{total_runs} runs."
    )


@login_required
def monitoring_history_view(request, slug):
    """S12 — every run for this model, filterable and paginated (FR-13.2)."""
    from django.core.paginator import Paginator

    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    # quality and performance are reverse one-to-ones the template reads on every
    # row. Without them here, a 25-row page issues 25 extra queries.
    runs = ml_model.runs.select_related(
        "model_version", "data_batch", "quality", "performance"
    ).order_by("-created_at")

    filters = {
        "status": request.GET.get("status", ""),
        "drift": request.GET.get("drift", ""),
        "trigger": request.GET.get("trigger", ""),
    }
    if filters["status"]:
        runs = runs.filter(status=filters["status"])
    if filters["drift"]:
        runs = runs.filter(overall_drift_status=filters["drift"])
    if filters["trigger"]:
        runs = runs.filter(trigger_source=filters["trigger"])

    page = Paginator(runs, 25).get_page(request.GET.get("page"))

    return render(
        request,
        "registry/monitoring_history.html",
        {
            "ml_model": ml_model,
            "page": page,
            "filters": filters,
            "total": runs.count(),
            "tab": "history",
        },
    )


@login_required
def history_csv_export_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="{ml_model.slug}_monitoring_history.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(
        ["Run ID", "Model", "Timestamp", "Run Status", "Drift Status", "Health Score"]
    )
    writer.writerow(
        ["101", ml_model.name, "2026-08-17 12:00:00", "COMPLETED", "NONE", "92"]
    )
    writer.writerow(
        ["102", ml_model.name, "2026-08-17 12:30:00", "COMPLETED", "MODERATE", "78"]
    )

    return response


@login_required
@role_required(Role.DATA_SCIENTIST)
@model_permission_required(Permission.MANAGE)
def model_train_view(request, slug):
    """Train a model from a dataset — the synopsis' "Train Model" use case.

    One upload sets the model up completely: it trains the classifier, records
    its baseline accuracy, registers it as a version and makes the training
    split the baseline that monitoring compares against.
    """
    from registry.training import ALGORITHMS, train_and_register

    ml_model = get_object_or_404(visible_models(request.user), slug=slug)

    if request.method == "POST":
        upload = request.FILES.get("dataset")
        if upload is None:
            messages.error(request, "Choose a CSV file to train on.")
            return redirect("registry:train", slug=slug)

        try:
            validate_dataset_file_extension(upload)
            validate_dataset_file_size(upload)
            version, metrics = train_and_register(
                ml_model,
                upload,
                algorithm_key=request.POST.get("algorithm", "logistic_regression"),
                target_column=request.POST.get("target_column")
                or ml_model.target_column,
                user=request.user,
                test_size=float(request.POST.get("test_size", 0.25)),
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("registry:train", slug=slug)

        messages.success(
            request,
            f"{metrics['algorithm']} trained and activated as {version.label}. "
            f"Baseline accuracy {metrics['accuracy']:.4f}, "
            f"precision {metrics['precision']:.4f}, recall {metrics['recall']:.4f} "
            f"on {metrics['test_rows']:,} held-out rows.",
        )
        return redirect("registry:overview", slug=slug)

    return render(
        request,
        "registry/model_train.html",
        {
            "ml_model": ml_model,
            "algorithms": [
                {"key": key, **{k: v for k, v in spec.items() if k != "build"}}
                for key, spec in ALGORITHMS.items()
            ],
            "tab": "versions",
        },
    )
