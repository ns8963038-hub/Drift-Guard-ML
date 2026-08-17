import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv(
    "SECRET_KEY", "django-insecure-drift-guard-ml-dev-key-change-in-prod"
)

# Base defaults are the SAFE ones. dev.py opens them up; prod.py leaves them
# closed. Defaulting to DEBUG=True and ALLOWED_HOSTS=["*"] here meant that any
# settings module which forgot to override them would ship a debug server open
# to every host — the failure mode should be "refuses to serve", not "serves
# tracebacks to anyone".
DEBUG = False

ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # DriftGuard Apps
    "core",
    "accounts",
    "registry",
    "datasets",
    "monitoring",
    "alerts",
    "simulator",
    "dashboard",
    "apiv1",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise was a declared dependency but was never wired in, so with
    # DEBUG off nothing served the CSS — every page rendered as unstyled HTML.
    # It has to sit directly after SecurityMiddleware and before everything else.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.LoginActivityMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# DATABASE_URL makes the PRD NFR-13 claim real: moving to PostgreSQL or MySQL is
# a settings change, not a code change, because every query goes through the ORM.
# Defaults to SQLite so a demo machine needs no database server.
import environ  # noqa: E402

_env = environ.Env()
DATABASES = {
    "default": _env.db_url(
        "DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
    )
}


AUTH_USER_MODEL = "accounts.User"

# Django's @login_required sends unauthenticated users to LOGIN_URL, which
# defaults to "/accounts/login/". This project serves login at "/login/", so
# without these three settings every logged-out visit lands on a 404 instead of
# the sign-in form — including a session that simply expired.
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email Configuration
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "False").lower() in ("true", "1", "yes")


# ── Scheduler ─────────────────────────────────────────────────────────
# In-process APScheduler. Disabled during tests, where a background thread
# ticking against a test database causes nothing but flakiness.
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "True") == "True"
SIMULATOR_DEFAULT_INTERVAL_SECONDS = int(
    os.getenv("SIMULATOR_DEFAULT_INTERVAL_SECONDS", "30")
)
BATCH_FILE_RETENTION_DAYS = int(os.getenv("BATCH_FILE_RETENTION_DAYS", "30"))


# ── Logging — TRD §12 ─────────────────────────────────────────────────
# Without this, a failed monitoring run's traceback and every scheduler error
# go nowhere. Those are precisely the events you need to see when something
# misbehaves during a demo, and they happen on a background thread where
# nobody is watching the console.
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname:<8} {name:<24} {message}",
            "style": "{",
        },
        "brief": {"format": "{levelname} {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "brief",
            "level": "INFO",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "driftguard.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "standard",
            "level": "INFO",
        },
    },
    "loggers": {
        # The named loggers the application writes to.
        "driftguard": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["file"],
            "level": "ERROR",
            "propagate": False,
        },
    },
    "root": {"handlers": ["file"], "level": "WARNING"},
}
