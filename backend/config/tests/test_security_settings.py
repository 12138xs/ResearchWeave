from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings import validate_production_settings


VALID_PRODUCTION_ENV = {
    "RESEARCH_OS_ENV": "production",
    "SECRET_KEY": "prod-secret-key-with-enough-length-123",
    "POSTGRES_PASSWORD": "prod-database-password",
    "ALLOWED_HOSTS": "research.example.org",
    "CSRF_TRUSTED_ORIGINS": "https://research.example.org",
    "PUBLIC_BASE_URL": "https://research.example.org",
}


class ProductionSettingsValidationTests(SimpleTestCase):
    def assert_rejected(self, field: str, value: str, message: str | None = None) -> None:
        env = VALID_PRODUCTION_ENV.copy()
        env[field] = value
        with self.assertRaisesMessage(ImproperlyConfigured, message or field):
            validate_production_settings(env)

    def test_production_accepts_complete_explicit_settings(self) -> None:
        validate_production_settings(VALID_PRODUCTION_ENV.copy())

    def test_production_rejects_missing_required_settings(self) -> None:
        for field in [
            "SECRET_KEY",
            "POSTGRES_PASSWORD",
            "ALLOWED_HOSTS",
            "CSRF_TRUSTED_ORIGINS",
            "PUBLIC_BASE_URL",
        ]:
            self.assert_rejected(field, "")

    def test_production_rejects_placeholder_required_settings(self) -> None:
        placeholders = {
            "SECRET_KEY": "replace-with-a-long-random-django-secret-key",
            "POSTGRES_PASSWORD": "replace-with-a-strong-database-password",
            "ALLOWED_HOSTS": "example.internal",
            "CSRF_TRUSTED_ORIGINS": "http://example.internal",
            "PUBLIC_BASE_URL": "change-me",
        }

        for field, value in placeholders.items():
            self.assert_rejected(field, value)

    def test_production_rejects_wildcard_allowed_hosts(self) -> None:
        self.assert_rejected("ALLOWED_HOSTS", "*")

    def test_development_allows_local_defaults(self) -> None:
        validate_production_settings({"RESEARCH_OS_ENV": "development"})
