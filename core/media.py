"""Finding media files that nothing points at any more.

Django deletes rows, never the files those rows referenced. Re-seeding the demo
therefore left every previous artifact, baseline and batch on disk: after a few
runs, 24 of the 30 files under MEDIA_ROOT belonged to models that no longer
existed, and they made up 29 of the 40 MB — most of which then travelled to the
client inside the release bundle.
"""

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import models


def referenced_media() -> set[Path]:
    """Absolute paths of every file some row still points at.

    Every FileField on every model is consulted rather than a fixed list, so a
    new model with an upload cannot quietly have its files treated as rubbish.
    """
    root = Path(settings.MEDIA_ROOT)
    keep: set[Path] = set()

    for model in apps.get_models():
        fields = [
            field.name
            for field in model._meta.get_fields()
            if isinstance(field, models.FileField)
        ]
        if not fields:
            continue
        for row in model._default_manager.all().only("pk", *fields).iterator():
            for name in fields:
                value = getattr(row, name, None)
                if value and value.name:
                    keep.add((root / value.name).resolve())
    return keep


def orphaned_media() -> list[Path]:
    """Files under MEDIA_ROOT that no row references, newest last."""
    root = Path(settings.MEDIA_ROOT)
    if not root.exists():
        return []
    keep = referenced_media()
    found = [
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    ]
    return sorted(set(found) - keep)


def prune_orphaned_media() -> tuple[int, int]:
    """Delete unreferenced files. Returns (files removed, bytes reclaimed)."""
    removed = 0
    freed = 0
    for path in orphaned_media():
        try:
            freed += path.stat().st_size
            path.unlink()
            removed += 1
        except OSError:
            # A file that cannot be removed is not worth failing a reseed over.
            continue

    # Tidy up any directories the deletions left empty.
    root = Path(settings.MEDIA_ROOT)
    if root.exists():
        for directory in sorted(root.rglob("*"), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()

    return removed, freed
