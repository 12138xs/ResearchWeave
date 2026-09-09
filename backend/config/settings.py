from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[1]


PLACEHOLDER_VALUES = {
    "",
    "*",
    "change-me",
    "dev-only-change-me",
    "example.internal",
    "localhost",
    "password",
    "replace-with-a-long-random-django-secret-key",
    "replace-with-a-strong-database-password",
    "secret",
}


def _split_env_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _is_placeholder(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in PLACEHOLDER_VALUES or normalized.startswith("replace-with-")


def _has_placeholder(values: list[str]) -> bool:
    return any(_is_placeholder(value) for value in values)


def _is_placeholder_url(value: str | None) -> bool:
    value = str(value or "").strip()
    if _is_placeholder(value):
        return True
    parsed = urlsplit(value)
    return _is_placeholder(parsed.hostname or "")


def validate_production_settings(env=os.environ) -> None:
    if env.get("RESEARCH_OS_ENV", "development") != "production":
        return

    if _is_placeholder(env.get("SECRET_KEY")) or len(str(env.get("SECRET_KEY", ""))) < 24:
        raise ImproperlyConfigured("SECRET_KEY must be explicitly configured for production.")
    if _is_placeholder(env.get("POSTGRES_PASSWORD")):
        raise ImproperlyConfigured("POSTGRES_PASSWORD must be explicitly configured for production.")
    allowed_hosts = _split_env_list(env.get("ALLOWED_HOSTS", ""))
    if not allowed_hosts or _has_placeholder(allowed_hosts):
        raise ImproperlyConfigured("ALLOWED_HOSTS must list explicit production hosts.")
    csrf_trusted_origins = _split_env_list(env.get("CSRF_TRUSTED_ORIGINS", ""))
    if not csrf_trusted_origins or any(_is_placeholder_url(value) for value in csrf_trusted_origins):
        raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS must be configured for production.")
    public_base_url = str(env.get("PUBLIC_BASE_URL", "")).strip()
    if _is_placeholder_url(public_base_url) or public_base_url == "http://localhost:30888":
        raise ImproperlyConfigured("PUBLIC_BASE_URL must be configured for production.")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("RESEARCH_OS_ENV", "development") != "production"
APP_VERSION = os.getenv("APP_VERSION", "")
ALLOWED_HOSTS = [
    item.strip()
    for item in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if item.strip()
]
CSRF_TRUSTED_ORIGINS = [
    item.strip()
    for item in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if item.strip()
]

validate_production_settings()

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "apps.accounts",
    "apps.library",
    "apps.documents",
    "apps.papers",
    "apps.experiments",
    "apps.annotations",
    "apps.search",
    "apps.ai",
    "apps.assistant",
    "apps.quality",
    "apps.research_map",
    "apps.tasks",
    "apps.storage",
    "apps.materials",
    "apps.exports",
]

MIDDLEWARE = [
    "apps.common.middleware.PrivateAPIResponseMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "research_os"),
        "USER": os.getenv("POSTGRES_USER", "research_os"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "research_os"),
        "HOST": os.getenv("POSTGRES_HOST", "postgres"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
}

STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", BASE_DIR / "storage"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:30888")
PAPER_UPLOAD_MAX_BYTES = int(os.getenv("PAPER_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
PAPER_UPLOAD_MAX_PAGES = int(os.getenv("PAPER_UPLOAD_MAX_PAGES", "300"))
PAPER_UPLOAD_ALLOWED_CIDRS = [
    item.strip()
    for item in os.getenv(
        "PAPER_UPLOAD_ALLOWED_CIDRS",
        "127.0.0.1/32,10.89.0.0/24",
    ).split(",")
    if item.strip()
]
PAPER_TRUSTED_PROXY_CIDRS = [
    item.strip()
    for item in os.getenv("PAPER_TRUSTED_PROXY_CIDRS", "127.0.0.1/32,10.89.0.0/24").split(",")
    if item.strip()
]
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(64 * 1024 * 1024)))
PAPER_DEEP_PARSER_PROVIDER = os.getenv("PAPER_DEEP_PARSER_PROVIDER", "placeholder")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
REDIS_URL = os.getenv("REDIS_URL", CELERY_BROKER_URL)
CELERY_TASK_DEFAULT_QUEUE = "fast_q"
CELERY_TASK_ROUTES = {
    "apps.tasks.celery_tasks.fast_ping": {"queue": "fast_q"},
    "apps.tasks.celery_tasks.ai_ping": {"queue": "ai_q"},
    "apps.tasks.celery_tasks.heavy_ping": {"queue": "heavy_q"},
    "apps.papers.tasks.run_paper_deep_process_task": {"queue": "heavy_q"},
    "apps.experiments.tasks.run_experiment_task": {"queue": "heavy_q"},
    "apps.search.tasks.reindex_search_task": {"queue": "fast_q"},
    "apps.quality.tasks.run_quality_audit_task": {"queue": "fast_q"},
    "apps.research_map.tasks.generate_direction_map_task": {"queue": "fast_q"},
}
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

MODEL_GATEWAY_PROVIDER = os.getenv("MODEL_GATEWAY_PROVIDER", "disabled")
MODEL_GATEWAY_BASE_URL = os.getenv("MODEL_GATEWAY_BASE_URL", "https://api.minimaxi.com/v1")
MODEL_GATEWAY_API_KEY = os.getenv("MODEL_GATEWAY_API_KEY", "")
DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "MiniMax-M2.7")
MODEL_GATEWAY_TIMEOUT_SECONDS = int(os.getenv("MODEL_GATEWAY_TIMEOUT_SECONDS", "60"))
MODEL_GATEWAY_MAX_TOKENS = int(os.getenv("MODEL_GATEWAY_MAX_TOKENS", "1600"))
MODEL_GATEWAY_CONTEXT_TOKEN_LIMIT = int(os.getenv("MODEL_GATEWAY_CONTEXT_TOKEN_LIMIT", "24000"))
PAPER_DEEP_LLM_TIMEOUT_SECONDS = int(os.getenv("PAPER_DEEP_LLM_TIMEOUT_SECONDS", "180"))
PAPER_DEEP_LLM_MAX_TOKENS = int(os.getenv("PAPER_DEEP_LLM_MAX_TOKENS", "5200"))
PAPER_DEEP_LLM_EXCERPT_MAX_CHARS = int(os.getenv("PAPER_DEEP_LLM_EXCERPT_MAX_CHARS", "32000"))
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "disabled")
WEB_SEARCH_ENDPOINT = os.getenv("WEB_SEARCH_ENDPOINT", "")
WEB_SEARCH_API_KEY = os.getenv("WEB_SEARCH_API_KEY", "")
WEB_SEARCH_TIMEOUT_SECONDS = int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "12"))
