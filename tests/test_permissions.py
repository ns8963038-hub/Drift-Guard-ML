import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from accounts.models import User, ModelAccess
from registry.models import MLModel
from core.constants import Role, Permission, ProblemType
from core.mixins import visible_models


@pytest.mark.django_db
def test_visible_models():
    admin = User.objects.create_user(username="admin", password="p", role=Role.ADMIN)
    owner = User.objects.create_user(username="owner", password="p", role=Role.ANALYST)
    other = User.objects.create_user(username="other", password="p", role=Role.ANALYST)

    m1 = MLModel.objects.create(
        name="Model A",
        slug="model-a",
        target_column="churn",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )
    MLModel.objects.create(
        name="Model B",
        slug="model-b",
        target_column="income",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )

    # Admin sees all models
    assert visible_models(admin).count() == 2

    # Owner sees owned models
    assert visible_models(owner).count() == 2

    # Other sees 0 models
    assert visible_models(other).count() == 0

    # Grant Model A to other
    ModelAccess.objects.create(user=other, ml_model=m1, permission=Permission.VIEW)
    assert visible_models(other).count() == 1
    assert visible_models(other).first() == m1


@pytest.mark.django_db
def test_admin_user_list_access(client):
    User.objects.create_user(username="engineer", password="p", role=Role.ANALYST)
    User.objects.create_user(username="admin", password="p", role=Role.ADMIN)

    url = reverse("accounts:user_list")

    # Analyst gets 403
    client.login(username="engineer", password="p")
    response = client.get(url)
    assert response.status_code == 403

    # Admin gets 200
    client.login(username="admin", password="p")
    response = client.get(url)
    assert response.status_code == 200


# ──────────────────────────────────────────────────────────────────────
# PRD §5.2 — the full permission matrix
#
# Phase 1's acceptance criterion is that *every row* of the matrix has a
# passing test. It is written out row by row rather than as a loop over a
# table, so a reviewer can put this file beside PRD §5.2 and check them off.
#
# This is the gate that would have caught registry/views.py shipping with
# @login_required and no role check, which let an Analyst create models
# and reach the version upload form.
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def people(db):
    """One user of each role, plus a model owned by the Data Scientist."""
    admin = User.objects.create_user(username="a", password="p", role=Role.ADMIN)
    scientist = User.objects.create_user(
        username="ds", password="p", role=Role.DATA_SCIENTIST
    )
    engineer = User.objects.create_user(username="eng", password="p", role=Role.ANALYST)
    outsider = User.objects.create_user(username="out", password="p", role=Role.ANALYST)

    ml_model = MLModel.objects.create(
        name="Churn",
        slug="churn",
        target_column="Churn",
        problem_type=ProblemType.BINARY,
        owner=scientist,
    )
    ModelAccess.objects.create(
        user=engineer, ml_model=ml_model, permission=Permission.VIEW
    )
    return {
        "admin": admin,
        "scientist": scientist,
        "engineer": engineer,
        "outsider": outsider,
        "model": ml_model,
    }


def _reach(client, user, url, method="get", data=None):
    """True when `user` can reach `url` — i.e. is not blocked by 403/404."""
    client.force_login(user)
    try:
        response = getattr(client, method)(url, data or {})
    except PermissionDenied:
        return False
    return response.status_code not in (403, 404)


# ── Row: Create / edit / deactivate users — Admin only ────────────────


def test_matrix_manage_users(client, people):
    url = reverse("accounts:user_list")
    assert _reach(client, people["admin"], url) is True
    assert _reach(client, people["scientist"], url) is False
    assert _reach(client, people["engineer"], url) is False


# ── Row: Grant or revoke model access — Admin only ────────────────────


def test_matrix_manage_access_grants(client, people):
    url = reverse("accounts:access_grants")
    assert _reach(client, people["admin"], url) is True
    assert _reach(client, people["scientist"], url) is False
    assert _reach(client, people["engineer"], url) is False


# ── Row: View login activity (all users) — Admin only ─────────────────


def test_matrix_view_login_activity(client, people):
    url = reverse("accounts:login_activity")
    assert _reach(client, people["admin"], url) is True
    assert _reach(client, people["scientist"], url) is False
    assert _reach(client, people["engineer"], url) is False


# ── Row: View own profile — every role ────────────────────────────────


def test_matrix_view_own_profile(client, people):
    url = reverse("accounts:profile")
    for role in ("admin", "scientist", "engineer"):
        assert _reach(client, people[role], url) is True, role


# ── Row: Create model — Admin + Data Scientist, NOT Analyst ───────


def test_matrix_create_model_is_denied_to_analyst(client, people):
    """The bug this file exists to prevent.

    An Analyst reaching this view could create models, and from there the
    version upload screen — which accepts pickled artifacts that execute code
    on load. Restricting upload to Admin and Data Scientist is the stated
    mitigation for accepted risk R1, so this row is a security control.
    """
    url = reverse("registry:create")
    assert _reach(client, people["admin"], url) is True
    assert _reach(client, people["scientist"], url) is True
    assert _reach(client, people["engineer"], url) is False


@pytest.mark.django_db
def test_matrix_analyst_cannot_create_a_model_by_post(client, people):
    """Verified at the data layer, not just the response code."""
    before = MLModel.objects.count()
    client.force_login(people["engineer"])
    try:
        client.post(
            reverse("registry:create"),
            {
                "name": "Sneaky",
                "target_column": "y",
                "problem_type": ProblemType.BINARY,
            },
        )
    except PermissionDenied:
        pass
    assert MLModel.objects.count() == before, "an Analyst created a model"


# ── Row: Upload model version — Admin + Data Scientist with MANAGE ────


def test_matrix_upload_version(client, people):
    url = reverse("registry:version_upload", args=[people["model"].slug])
    assert _reach(client, people["admin"], url) is True
    assert _reach(client, people["scientist"], url) is True
    assert _reach(client, people["engineer"], url) is False, "VIEW grant is not enough"


# ── Row: Edit threshold profile — Admin + Data Scientist with MANAGE ──


def test_matrix_edit_thresholds(client, people):
    url = reverse("alerts:thresholds", args=[people["model"].slug])
    assert _reach(client, people["admin"], url) is True
    assert _reach(client, people["scientist"], url) is True
    assert _reach(client, people["engineer"], url) is False


# ── Row: View model dashboards / drift / history — granted users ──────


def test_matrix_view_granted_model(client, people):
    for name in ("overview", "versions"):
        url = reverse(f"registry:{name}", args=[people["model"].slug])
        assert _reach(client, people["admin"], url) is True, name
        assert _reach(client, people["scientist"], url) is True, name
        assert _reach(client, people["engineer"], url) is True, name


def test_matrix_ungranted_model_is_unreachable(client, people):
    """FR-01.7 — and indistinguishable from the model not existing."""
    url = reverse("registry:overview", args=[people["model"].slug])
    assert _reach(client, people["outsider"], url) is False


# ── Row: Compare versions — granted users ─────────────────────────────


def test_matrix_version_comparison(client, people):
    url = reverse("registry:compare", args=[people["model"].slug])
    assert _reach(client, people["engineer"], url) is True
    assert _reach(client, people["outsider"], url) is False


# ── Row: Monitoring history — granted users ───────────────────────────


def test_matrix_monitoring_history(client, people):
    url = reverse("registry:history", args=[people["model"].slug])
    assert _reach(client, people["engineer"], url) is True
    assert _reach(client, people["outsider"], url) is False


# ── Row: View + acknowledge alerts — granted users ────────────────────


def test_matrix_alerts_list(client, people):
    url = reverse("alerts:list")
    for role in ("admin", "scientist", "engineer"):
        assert _reach(client, people[role], url) is True, role


# ── Row: Retraining recommendations — granted users ───────────────────


def test_matrix_recommendations(client, people):
    url = reverse("alerts:recommendations")
    for role in ("admin", "scientist", "engineer"):
        assert _reach(client, people[role], url) is True, role


# ── Row: Dashboard — every role, scoped to what they may see ──────────


def test_matrix_dashboard(client, people):
    url = reverse("dashboard:index")
    for role in ("admin", "scientist", "engineer"):
        assert _reach(client, people[role], url) is True, role


# ── Cross-cutting: nothing is reachable while logged out ──────────────


def test_matrix_anonymous_is_locked_out(client, people):
    """Logged-out users are redirected, and the redirect must actually work.

    This previously asserted only `status_code in (302, 403)`, which a redirect
    to a non-existent URL satisfies. LOGIN_URL was unset, so Django sent people
    to its default /accounts/login/ — a 404 — and the test passed anyway.
    Following the redirect is what makes the assertion mean something.
    """
    for url in [
        reverse("dashboard:index"),
        reverse("registry:list"),
        reverse("alerts:list"),
        reverse("accounts:user_list"),
    ]:
        response = client.get(url, follow=True)
        assert response.status_code == 200, f"{url} redirected somewhere broken"
        # Assert on the form itself rather than its heading text — a login page
        # is defined by having somewhere to type a username, not by its wording.
        assert (
            b'name="username"' in response.content
        ), f"{url} did not land on a page with a login form"
        assert response.redirect_chain, f"{url} was served without authentication"


def test_login_url_setting_matches_the_real_login_route(client):
    """Guards the specific mismatch above: the setting and the route must agree."""
    from django.conf import settings

    assert settings.LOGIN_URL == reverse("accounts:login")
    assert client.get(settings.LOGIN_URL).status_code == 200


@pytest.mark.django_db
def test_renaming_a_user_onto_a_taken_username_is_rejected_not_a_500(client):
    """The uniqueness check existed only on the create path.

    Renaming an existing user onto a taken name reached save() and raised
    IntegrityError — a 500 on an ordinary typo.
    """
    User.objects.create_user(username="root", password="p", role=Role.ADMIN)
    User.objects.create_user(username="taken", password="p", role=Role.ANALYST)
    victim = User.objects.create_user(
        username="victim", password="p", role=Role.ANALYST
    )
    client.login(username="root", password="p")

    response = client.post(
        reverse("accounts:user_edit", args=[victim.id]),
        {"username": "taken", "email": "", "role": Role.ANALYST, "is_active": "on"},
    )
    assert response.status_code == 200
    assert "already taken" in response.content.decode()
    victim.refresh_from_db()
    assert victim.username == "victim"


@pytest.mark.django_db
def test_an_admin_cannot_lock_themselves_out(client):
    """Demoting or deactivating yourself removes the only way back in."""
    admin = User.objects.create_user(username="solo", password="p", role=Role.ADMIN)
    client.login(username="solo", password="p")
    url = reverse("accounts:user_edit", args=[admin.id])

    demote = client.post(
        url, {"username": "solo", "email": "", "role": Role.ANALYST, "is_active": "on"}
    )
    assert "cannot remove your own Administrator role" in demote.content.decode()

    deactivate = client.post(url, {"username": "solo", "email": "", "role": Role.ADMIN})
    assert "cannot deactivate your own account" in deactivate.content.decode()

    admin.refresh_from_db()
    assert admin.role == Role.ADMIN and admin.is_active


@pytest.mark.django_db
def test_blank_username_is_rejected_rather_than_raising(client):
    """create_user() raises ValueError on a blank username — a 500, not a message."""
    User.objects.create_user(username="root2", password="p", role=Role.ADMIN)
    client.login(username="root2", password="p")

    response = client.post(
        reverse("accounts:user_create"),
        {"username": "  ", "email": "", "role": Role.ANALYST, "password": "x"},
    )
    assert response.status_code == 200
    assert "username is required" in response.content.decode()


@pytest.mark.django_db
def test_rejected_user_form_keeps_what_was_typed(client):
    User.objects.create_user(username="root3", password="p", role=Role.ADMIN)
    User.objects.create_user(username="clash", password="p", role=Role.ANALYST)
    client.login(username="root3", password="p")

    response = client.post(
        reverse("accounts:user_create"),
        {
            "username": "clash",
            "email": "keep@me.test",
            "role": Role.DATA_SCIENTIST,
            "password": "x",
        },
    )
    body = response.content.decode()
    assert 'value="clash"' in body
    assert 'value="keep@me.test"' in body


@pytest.mark.django_db
def test_model_screens_state_your_access_level(client):
    """Role alone does not say what you may do on a *specific* model.

    A Data Scientist and an Analyst saw an identical model list and an identical
    model header, so nothing on either screen distinguished the account that can
    configure a model from the one that can only read it.
    """
    from accounts.models import ModelAccess
    from core.constants import Permission
    from registry.models import MLModel

    owner = User.objects.create_user(
        username="owner1", password="p", role=Role.DATA_SCIENTIST
    )
    reader = User.objects.create_user(
        username="reader1", password="p", role=Role.ANALYST
    )
    model = MLModel.objects.create(
        name="Shared",
        slug="shared",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=owner,
    )
    ModelAccess.objects.create(user=reader, ml_model=model, permission=Permission.VIEW)

    client.login(username="owner1", password="p")
    owner_list = client.get(reverse("registry:list")).content.decode()
    owner_page = client.get(
        reverse("registry:overview", args=[model.slug])
    ).content.decode()
    assert "You own this" in owner_list
    assert "You own this" in owner_page

    client.login(username="reader1", password="p")
    reader_list = client.get(reverse("registry:list")).content.decode()
    reader_page = client.get(
        reverse("registry:overview", args=[model.slug])
    ).content.decode()
    assert "Read only" in reader_list
    assert "Read only" in reader_page
    assert "You own this" not in reader_list

    # The administrator reaches it without any grant at all.
    User.objects.create_user(username="boss1", password="p", role=Role.ADMIN)
    client.login(username="boss1", password="p")
    assert "Full access" in client.get(reverse("registry:list")).content.decode()
