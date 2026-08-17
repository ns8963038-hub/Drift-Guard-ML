"""Production settings.

The demo runs on dev.py; this exists so `manage.py check --deploy` is clean and
so the project is not one careless deployment away from serving tracebacks to
the internet. Every value below is what the check asks for.
"""

import os

from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Fail loudly rather than silently serving with the development key.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY must be set in the environment for production. "
        "Generate one with: python -c 'from django.core.management.utils import "
        "get_random_secret_key; print(get_random_secret_key())'"
    )

# ── HTTPS ─────────────────────────────────────────────────────────────
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True") == "True"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000  # one year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# ── Hardening ─────────────────────────────────────────────────────────
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Behind a reverse proxy terminating TLS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ── Scheduler ─────────────────────────────────────────────────────────
# The scheduler runs in-process, so exactly one worker may serve this app.
# Two workers means two schedulers and every simulated batch delivered twice.
# Run with: gunicorn --workers 1 config.wsgi
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "True") == "True"
