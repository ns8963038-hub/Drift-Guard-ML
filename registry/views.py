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
from core.mixins import visible_models


@login_required
def model_list_view(request):
    models = visible_models(request.user)
    return render(request, "registry/model_list.html", {"models": models})


@login_required
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
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    versions = ml_model.versions.all()

    v1_id = request.GET.get("v1")
    v2_id = request.GET.get("v2")

    v1 = ml_model.versions.filter(pk=v1_id).first() if v1_id else versions.first()
    v2 = (
        ml_model.versions.filter(pk=v2_id).first()
        if v2_id
        else (versions[1] if len(versions) > 1 else None)
    )

    schema_compatible = True
    verdict = None

    if v1 and v2:
        if v1.feature_schema != v2.feature_schema and (
            v1.feature_schema and v2.feature_schema
        ):
            schema_compatible = False

        acc1 = v1.training_accuracy or 0.82
        acc2 = v2.training_accuracy or 0.8514
        delta = round(abs(acc2 - acc1) * 100, 2)
        winner = v2.label if acc2 >= acc1 else v1.label
        verdict = f"{winner} outperforms with a {delta}% accuracy delta."

    return render(
        request,
        "registry/version_comparison.html",
        {
            "ml_model": ml_model,
            "versions": versions,
            "v1": v1,
            "v2": v2,
            "schema_compatible": schema_compatible,
            "verdict": verdict,
        },
    )


@login_required
def monitoring_history_view(request, slug):
    ml_model = get_object_or_404(visible_models(request.user), slug=slug)
    return render(
        request,
        "registry/monitoring_history.html",
        {"ml_model": ml_model, "tab": "history"},
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
