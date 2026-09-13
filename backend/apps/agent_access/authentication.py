from __future__ import annotations

import hmac
import re
from uuid import UUID

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from apps.agent_access.models import AgentAccessToken


TOKEN_PATTERN = re.compile(rb"^rwv_pat_([0-9a-f]{32})\.([A-Za-z0-9_-]{32,128})$")


class PersonalAccessTokenAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header:
            return None
        if len(header) != 2 or header[0].lower() != b"bearer":
            raise AuthenticationFailed({"code": "invalid_token", "detail": "Bearer token format is invalid."})
        if not request.is_secure():
            raise AuthenticationFailed({
                "code": "insecure_transport",
                "detail": "Personal access tokens require HTTPS.",
            })
        match = TOKEN_PATTERN.fullmatch(header[1])
        if not match:
            raise AuthenticationFailed({"code": "invalid_token", "detail": "Personal access token is invalid."})
        try:
            token_id = UUID(hex=match.group(1).decode("ascii"))
        except ValueError as error:
            raise AuthenticationFailed({"code": "invalid_token", "detail": "Personal access token is invalid."}) from error
        record = AgentAccessToken.objects.select_related("owner").filter(token_id=token_id).first()
        secret = match.group(2).decode("ascii")
        if record is None or not hmac.compare_digest(record.secret_hash, AgentAccessToken.hash_secret(secret)):
            raise AuthenticationFailed({"code": "invalid_token", "detail": "Personal access token is invalid."})
        request._agent_token_candidate = record
        if record.revoked_at is not None:
            raise AuthenticationFailed({"code": "token_revoked", "detail": "Personal access token was revoked."})
        if record.expires_at is not None and record.expires_at <= timezone.now():
            raise AuthenticationFailed({"code": "token_expired", "detail": "Personal access token expired."})
        AgentAccessToken.objects.filter(pk=record.pk).update(last_used_at=timezone.now())
        return record.owner, record

    def authenticate_header(self, request):
        return self.keyword
