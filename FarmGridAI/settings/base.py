"""Base Django settings shared by every environment.

Development and production settings inherit from this module. Secrets are
never stored here - they are loaded from environment variables (``.env``).
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = os.getenv("khetsathi_ENV_FILE", BASE_DIR / ".env")
if Path(ENV_FILE).exists():
    load_dotenv(ENV_FILE)

# ---------------------------------------------------------------------------
# Security (defaults are safe for development; production overrides them)
# ---------------------------------------------------------------------------
# The signing key also keys the HS256 JWTs issued by SimpleJWT. PyJWT warns
# when an HMAC secret is under 32 bytes, so the development fallback is long
# enough to silence that and to keep every token comfortably inside the
# recommended strength. Production still requires an explicit key.
_SECRET_KEY_FALLBACK = "dev-insecure-secret-change-me-before-deploying-anywhere-real"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or _SECRET_KEY_FALLBACK
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",") if h.strip()]

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.farms",
    "apps.crops",
    "apps.equipment",
    "apps.expenses",
    "apps.energy",
    "apps.finance",
    "apps.subsidies",
    "apps.recommendations",
    "apps.ml_engine",
    "apps.chatbot",
    "apps.data_ingestion",
    "apps.api",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Must sit after SessionMiddleware and AuthenticationMiddleware so the
    # activated language can honour the signed-in user's saved preference.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
]

ROOT_URLCONF = "FarmGridAI.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "FarmGridAI-frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.web.page_media.page_background",
        "apps.web.i18n_context.i18n_context",
    ],
        },
    },
]

WSGI_APPLICATION = "FarmGridAI.wsgi.application"
ASGI_APPLICATION = "FarmGridAI.asgi.application"

# ---------------------------------------------------------------------------
# Database (PostgreSQL-ready with SQLite default for local development)
# ---------------------------------------------------------------------------
USE_POSTGRES = os.getenv("DB_ENGINE", "sqlite").lower() in {"postgres", "postgresql", "pg"}

if USE_POSTGRES:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "FarmGridAI"),
            "USER": os.getenv("DB_USER", "FarmGrid"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# The farmer-facing sign-in page lives at /login/ (not /admin/login/), so
# @login_required must point there and carry ?next= for the return trip.
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"

# ---------------------------------------------------------------------------
# Internationalization / language (English + Hindi)
# ---------------------------------------------------------------------------
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "en")
LANGUAGES = [
    ("en", "English"),
    ("hi", "Hindi"),
]
# User-facing copy is translated through apps.core.i18n_text (a Python catalog)
# and the `{% t %}` tag, so no compiled .mo files are needed. Django's own
# machinery is still switched on for dates/numbers and for `{% translate %}`.
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

# Preference is remembered per signed-in user; the `set_language` view falls
# back to a session for anonymous visitors so the choice survives navigation.
SESSION_COOKIE_NAME = "farmgrid_sessionid"

# Behind a TLS-terminating proxy - a Cloudflare tunnel, for instance - Django
# only sees plain HTTP on the loopback socket, so `request.is_secure()` is False
# even though the browser is on HTTPS. That mismatch quietly breaks anything
# keyed off it: secure cookies are issued without the Secure flag, and
# SECURE_SSL_REDIRECT logic can loop. Trusting the forwarded header is opt-in via
# TRUST_PROXY_HEADERS so a direct (unproxied) run is unaffected.
if os.getenv("TRUST_PROXY_HEADERS", "").lower() in {"1", "true", "yes"}:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "FarmGridAI-frontend" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Upload validation limits
MAX_UPLOAD_FILE_SIZE_MB = int(os.getenv("MAX_UPLOAD_FILE_SIZE_MB", "10"))
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_BILL_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "EXCEPTION_HANDLER": "apps.api.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "register": "10/hour",
        "login": "20/hour",
        "public": "120/hour",
        "user": "1000/hour",
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", "60"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "false").lower() in {"1", "true"}

# ---------------------------------------------------------------------------
# drf-spectacular (OpenAPI)
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "FarmGrid AI API",
    "DESCRIPTION": (
        "Personalized farm financial intelligence for Indian farmers. "
        "All analytical outputs are estimates with confidence, assumptions and limitations. "
        "Subsidy outputs are preliminary and require official verification."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ---------------------------------------------------------------------------
# Celery / Redis (app works synchronously when unavailable)
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "true").lower() in {"1", "true"}
CELERY_TASK_EAGER_PROPAGATES = True

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@khetsathi.example")

# ---------------------------------------------------------------------------
# Logging (privacy-aware: never log personal data)
# ---------------------------------------------------------------------------
# The audit FileHandler is constructed during django.setup(), so its directory
# must already exist or every management command (and the server) fails to boot.
LOG_DIR = BASE_DIR / "logs"
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:  # read-only filesystem: fall back to console-only audit logging
    pass

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
        "simple": {"format": "{levelname} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "audit_file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "logs" / "audit.log",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "FarmGrid": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "khetsathi.audit": {"handlers": ["audit_file", "console"], "level": "INFO", "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# Django default fields
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

# ---------------------------------------------------------------------------
# ML model settings
# ---------------------------------------------------------------------------
ML_MODEL_DIR = BASE_DIR / "data" / "models"
ML_EQUIPMENT_CLASSIFIER_WEIGHTS = os.getenv("ML_EQUIPMENT_CLASSIFIER_WEIGHTS", "")
ML_EQUIPMENT_CLASSIFIER_ARCH = os.getenv("ML_EQUIPMENT_CLASSIFIER_ARCH", "mobilenet_v3_large")
ML_EQUIPMENT_CLASSIFIER_ARTIFACT_DIR = os.getenv("ML_EQUIPMENT_CLASSIFIER_ARTIFACT_DIR", str(ML_MODEL_DIR / "equipment_classifier"))
ML_EQUIPMENT_CLASSIFIER_ARTIFACT_FILE = os.getenv("ML_EQUIPMENT_CLASSIFIER_ARTIFACT_FILE", "equipment_classifier_mobilenetv3_top6_v1.pt")
ML_EQUIPMENT_CLASSIFIER_UNKNOWN_THRESHOLD = float(os.getenv("ML_EQUIPMENT_CLASSIFIER_UNKNOWN_THRESHOLD", "0.55"))
ML_EQUIPMENT_CLASSIFIER_ACTIVATION_MACRO_F1 = float(os.getenv("ML_EQUIPMENT_CLASSIFIER_ACTIVATION_MACRO_F1", "0.70"))
OCR_LIBRARY = os.getenv("OCR_LIBRARY", "auto")  # auto | easyocr | tesseract | none
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
CHATBOT_LLM_ENABLED = bool(LLM_API_KEY) and os.getenv("CHATBOT_LLM_ENABLED", "false").lower() in {"1", "true"}

# ---------------------------------------------------------------------------
# Data ingestion (web compliance & dataset enrichment)
# ---------------------------------------------------------------------------
# Networking is OFF by default. It is only turned on explicitly for an
# approved DataSource during a single collection run.
DATA_INGESTION_NETWORK_ALLOWED = os.getenv("DATA_INGESTION_NETWORK_ALLOWED", "false").lower() in {"1", "true"}
DATA_INGESTION_DATA_DIR = os.getenv("DATA_INGESTION_DATA_DIR", str(BASE_DIR / "data" / "ingested"))
DATA_INGESTION_REPORTS_DIR = os.getenv("DATA_INGESTION_REPORTS_DIR", str(BASE_DIR / "data" / "ingested" / "reports"))
DATA_INGESTION_IMPORT_DIR = os.getenv("DATA_INGESTION_IMPORT_DIR", str(BASE_DIR / "data" / "imports"))
DATA_INGESTION_USER_AGENT = os.getenv("DATA_INGESTION_USER_AGENT", "FarmGridAI-ResearchBot/1.0 (+{contact})")
DATA_INGESTION_CONTACT_EMAIL = os.getenv("DATA_INGESTION_CONTACT_EMAIL", "")
DATA_INGESTION_DEFAULT_HTTP_TIMEOUT_SECONDS = int(os.getenv("DATA_INGESTION_HTTP_TIMEOUT", "15"))
DATA_INGESTION_MAX_ARTIFACT_SIZE_MB = int(os.getenv("DATA_INGESTION_MAX_ARTIFACT_SIZE_MB", "25"))
DATA_INGESTION_MAX_IMAGE_SIZE_MB = int(os.getenv("DATA_INGESTION_MAX_IMAGE_SIZE_MB", "15"))
DATA_INGESTION_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DATA_INGESTION_ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
DATA_INGESTION_MIN_IMAGE_DIMENSION = int(os.getenv("DATA_INGESTION_MIN_IMAGE_DIMENSION", "320"))
DATA_INGESTION_DEFAULT_RATE_LIMIT_PER_MINUTE = int(os.getenv("DATA_INGESTION_DEFAULT_RATE_LIMIT", "10"))
DATA_INGESTION_DEFAULT_REQUEST_DELAY_SECONDS = float(os.getenv("DATA_INGESTION_DEFAULT_REQUEST_DELAY", "1.0"))
DATA_INGESTION_ROBOTS_USER_AGENT = os.getenv("DATA_INGESTION_ROBOTS_USER_AGENT", "FarmGridAIResearchBot")