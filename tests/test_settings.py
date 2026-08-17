def test_whitenoise_is_wired_in_so_static_files_survive_debug_off():
    """WhiteNoise was a dependency that nothing used.

    With DEBUG off, runserver stops serving static files and Django has no
    other handler, so every page rendered as unstyled HTML — including the
    403 and 404 pages, which only appear when DEBUG is off.
    """
    from django.conf import settings

    middleware = settings.MIDDLEWARE
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in middleware
    # It must run before everything except SecurityMiddleware.
    assert middleware.index("whitenoise.middleware.WhiteNoiseMiddleware") == 1


def test_dev_debug_can_be_switched_off_by_environment(monkeypatch):
    """The demo has to run with DEBUG off, or Django's debug 404 -- which lists
    every URL pattern -- replaces the project's own 404."""
    import importlib
    import os

    monkeypatch.setitem(os.environ, "DJANGO_DEBUG", "0")
    dev = importlib.import_module("config.settings.dev")
    importlib.reload(dev)
    assert dev.DEBUG is False

    monkeypatch.setitem(os.environ, "DJANGO_DEBUG", "1")
    importlib.reload(dev)
    assert dev.DEBUG is True
