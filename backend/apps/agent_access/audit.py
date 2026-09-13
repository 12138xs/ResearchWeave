from __future__ import annotations

import time
from uuid import UUID, uuid4

from apps.agent_access.models import AgentAccessToken, AgentAuditEvent


def request_id_for(request) -> UUID:
    value = str(request.headers.get("X-Request-ID", "")).strip()
    try:
        return UUID(value) if value else uuid4()
    except ValueError:
        return uuid4()


def response_error_code(response) -> str:
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        code = data.get("code")
        if isinstance(code, str):
            return code[:80]
        detail = data.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("code"), str):
            return detail["code"][:80]
    return ""


def response_count(response):
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if isinstance(results, list):
        return len(results)
    count = data.get("count")
    return count if isinstance(count, int) and count >= 0 else None


class AuditedAgentAPIViewMixin:
    audit_action = "unknown"

    def dispatch(self, request, *args, **kwargs):
        self._audit_started = time.monotonic()
        return super().dispatch(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        request_id = request_id_for(request)
        response["X-Request-ID"] = str(request_id)
        auth = request.auth if isinstance(request.auth, AgentAccessToken) else None
        candidate = getattr(request, "_agent_token_candidate", None)
        bearer_attempt = str(request.headers.get("Authorization", "")).lower().startswith("bearer ")
        audit_token = auth or (candidate if isinstance(candidate, AgentAccessToken) else None)
        if auth is not None or bearer_attempt:
            AgentAuditEvent.objects.create(
                request_id=request_id,
                user=(auth.owner if auth is not None else audit_token.owner if audit_token is not None else None),
                token=audit_token,
                client=str(request.headers.get("X-ResearchWeave-Client", ""))[:120],
                action=self.audit_action,
                method=request.method[:12],
                path=request.path[:300],
                status_code=response.status_code,
                error_code=response_error_code(response),
                returned_count=response_count(response),
                duration_ms=max(0, round((time.monotonic() - self._audit_started) * 1000)),
            )
        return response
