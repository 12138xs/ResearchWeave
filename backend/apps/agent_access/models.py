from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone


READ_SCOPES = frozenset({"materials:read", "evidence:read"})
KNOWN_SCOPES = READ_SCOPES


class AgentAccessToken(models.Model):
    token_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="agent_access_tokens", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    secret_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    @staticmethod
    def hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @classmethod
    def issue(cls, *, owner, name: str, scopes: list[str], expires_at=None):
        normalized_scopes = sorted(set(scopes))
        unknown = set(normalized_scopes) - KNOWN_SCOPES
        if unknown:
            raise ValueError(f"unknown scopes: {', '.join(sorted(unknown))}")
        secret = secrets.token_urlsafe(32)
        record = cls.objects.create(
            owner=owner,
            name=name,
            secret_hash=cls.hash_secret(secret),
            scopes=normalized_scopes,
            expires_at=expires_at,
        )
        raw_token = f"rwv_pat_{record.token_id.hex}.{secret}"
        return record, raw_token

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class AgentAuditEvent(models.Model):
    request_id = models.UUIDField(default=uuid4, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    token = models.ForeignKey(AgentAccessToken, null=True, on_delete=models.SET_NULL)
    client = models.CharField(max_length=120, blank=True)
    action = models.CharField(max_length=120)
    method = models.CharField(max_length=12)
    path = models.CharField(max_length=300)
    status_code = models.PositiveSmallIntegerField()
    error_code = models.CharField(max_length=80, blank=True)
    returned_count = models.PositiveIntegerField(null=True)
    duration_ms = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
