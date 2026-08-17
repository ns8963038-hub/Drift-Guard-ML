import os
import sys

from .base import *  # noqa: F403

# DEBUG on gives tracebacks while developing, which is what this module is for.
# It also replaces the project's own 403 and 404 pages with Django's debug
# pages — and the debug 404 lists every URL pattern in the project. That makes
# it the wrong setting for a demo: the walkthrough asks the reader to confirm
# that an ungranted model 404s and reveals nothing, and under DEBUG the page
# would hand them the whole URL map.
#
#   DJANGO_DEBUG=0 python manage.py runserver --noreload
#
# runs the demo with the real error pages.
DEBUG = os.environ.get("DJANGO_DEBUG", "1") != "0"
ALLOWED_HOSTS = ["*"]

# A background scheduler ticking against a test database produces flaky runs
# and stray writes, so it is off whenever pytest or manage.py test is driving.
if "pytest" in sys.modules or "test" in sys.argv:
    SCHEDULER_ENABLED = False

# Serve static files straight from STATICFILES_DIRS, so running the demo with
# DJANGO_DEBUG=0 does not additionally require a collectstatic step.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
