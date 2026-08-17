"""Media files whose rows are gone.

Django deletes rows, not files. Nothing reclaimed the difference.
"""

import pytest

from accounts.models import User
from core.constants import ProblemType, Role
from registry.models import MLModel, ModelVersion


@pytest.mark.django_db
def test_orphaned_media_is_found_and_removed(tmp_path, settings):
    """Django deletes rows but never their files.

    Re-seeding the demo left every previous artifact on disk — 24 of 30 files
    and 29 of 40 MB — and those dead files then travelled to the client inside
    the release bundle.
    """
    from core.media import orphaned_media, prune_orphaned_media

    settings.MEDIA_ROOT = tmp_path
    (tmp_path / "artifacts").mkdir()
    live = tmp_path / "artifacts" / "live.joblib"
    dead = tmp_path / "artifacts" / "dead.joblib"
    live.write_bytes(b"x" * 100)
    dead.write_bytes(b"y" * 200)

    user = User.objects.create_user(username="mu", password="p", role=Role.ANALYST)
    model = MLModel.objects.create(
        name="M",
        slug="m",
        target_column="t",
        problem_type=ProblemType.BINARY,
        owner=user,
    )
    ModelVersion.objects.create(
        ml_model=model, label="V1", artifact="artifacts/live.joblib"
    )

    assert orphaned_media() == [dead.resolve()]

    removed, freed = prune_orphaned_media()
    assert removed == 1 and freed == 200
    assert live.exists() and not dead.exists()
    assert orphaned_media() == []
