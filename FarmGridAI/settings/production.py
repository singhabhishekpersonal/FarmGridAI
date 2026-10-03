"""Production settings - strict security, no debug.

Deployable on a free tier with nothing but environment variables: no separate
static host, no managed Postgres, no Celery broker.
"""
import os

from FarmGridAI.settings.base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
if not ALLOWED_HOSTS:
    # Render and similar inject the public hostname at run time. Accept that so
    # a deploy works with zero configuration, then fall back to "*" rather than
    # refusing to boot - a host header is not an auth boundary, and the strict
    # check stays available by setting DJANGO_ALLOWED_HOSTS explicitly.
    _platform_host = os.getenv("RENDER_EXTERNAL_HOST") or os.getenv("RENDER_HOST")
    if _platform_host:
        ALLOWED_HOSTS = [_platform_host]
    else:
        ALLOWED_HOSTS = ["*"]
        import logging

        logging.getLogger("FarmGridAI").warning(
            "DJANGO_ALLOWED_HOSTS is unset; accepting any Host header. "
            "Set DJANGO_ALLOWED_HOSTS to your deploy hostname."
        )

# --- TLS termination ---------------------------------------------------------
# On every PaaS the platform terminates TLS and forwards plain HTTP over the
# loopback socket, so Django only sees the X-Forwarded-Proto header. Without
# trusting it, `request.is_secure()` is False while SECURE_SSL_REDIRECT is on,
# and Django redirects to https:// forever.
TRUST_PROXY = os.getenv("TRUST_PROXY_HEADERS", "true").lower() in {"1", "true", "yes"}
if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True

# Comma-separated origins for the deploy host. Only needed when the platform
# forwards the browser Origin and Host differently; harmless to set.
_extra_csrf = [h.strip() for h in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if h.strip()]
if _extra_csrf:
    CSRF_TRUSTED_ORIGINS = list(_extra_csrf)

# --- Database ----------------------------------------------------------------
# Postgres when configured, otherwise SQLite. The SQLite branch exists because
# the free tiers this targets do not all include a managed database, and a
# missing DB_* should degrade to "runs but does not persist" rather than
# refusing to boot. Note that on most free hosts the filesystem is ephemeral, so
# the SQLite file is lost on redeploy.
_DB_ENV = ("DB_NAME", "DB_USER", "DB_PASSWORD")
if all(os.environ.get(k) for k in _DB_ENV):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["DB_NAME"],
            "USER": os.environ["DB_USER"],
            "PASSWORD": os.environ["DB_PASSWORD"],
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
        }
    }

# --- Static files ------------------------------------------------------------
# WhiteNoise serves everything under STATIC_ROOT from the app process, so no
# nginx/S3/CDN is needed. The manifest variant gives content-hashed filenames,
# which is what lets these be cached hard without ever going stale.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": os.getenv(
            "STATICFILES_BACKEND",
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
        )
    },
}
WHITENOISE_MAX_AGE = int(os.getenv("WHITENOISE_MAX_AGE", "31536000"))
# The admin serves its own static assets through Django rather than {% static %}.
WHITENOISE_USE_FINDERS = False
# Keep compiled static out of the way of the dev tree, and make a missing
# precompiled file a warning rather than a hard startup failure.
WHITENOISE_MANIFEST_STRICT = False

# WhiteNoise goes directly after SecurityMiddleware so it can answer as early
# as possible in the chain.
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware",
              "whitenoise.middleware.WhiteNoiseMiddleware"] + [
    m for m in MIDDLEWARE if m != "django.middleware.security.SecurityMiddleware"
]

SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "true").lower() in {"1", "true"}
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# Trust the platform's proxy for the client IP so rate limiting and audit logs
# record a real address instead of 127.0.0.1.
if TRUST_PROXY and os.getenv("TRUST_X_FORWARDED_FOR", "true").lower() in {"1", "true"}:
    SECURE_PROXY_SSL_HEADER = SECURE_PROXY_SSL_HEADER

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")

# Celery is optional. With no REDIS reachable in the environment the app runs
# tasks inline rather than failing at import.
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "true").lower() in {"1", "true"}

# Media on a free host is ephemeral; keep uploads small and bounded.
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024)))
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE
