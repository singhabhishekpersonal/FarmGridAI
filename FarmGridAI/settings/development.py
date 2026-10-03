"""Development settings - local, permissive, SQLite by default."""
import os
import sys

from FarmGridAI.settings.base import BASE_DIR  # noqa: F401
from FarmGridAI.settings import base as _base

# Import everything from the base settings module.
from FarmGridAI.settings.base import *  # noqa: F401,F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

# SQLite database for local development.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Run Celery tasks synchronously so no Redis is required.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

INSTALLED_APPS = list(INSTALLED_APPS)

# Bust the browser cache per file by putting the mtime in the static URL.
# runserver serves /static/ outside the middleware chain and sends no
# Cache-Control, so heuristic caching can keep an edited app.js running in an
# open tab. Versioned URLs make that impossible.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "FarmGridAI.staticfiles.VersionedStaticStorage"},
}

_extra_test_apps = [
    "django.contrib.staticfiles",
]

# pytest-django support.
if "test" in sys.argv or "TESTING" in os.environ:
    _base.LOGGING.get("loggers", {}).get("khetsathi.audit", {})["handlers"] = ["console"]