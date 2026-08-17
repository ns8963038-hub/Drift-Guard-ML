import sys
from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# A background scheduler ticking against a test database produces flaky runs
# and stray writes, so it is off whenever pytest or manage.py test is driving.
if "pytest" in sys.modules or "test" in sys.argv:
    SCHEDULER_ENABLED = False
