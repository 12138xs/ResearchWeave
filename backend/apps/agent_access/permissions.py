from django.conf import settings
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import BasePermission

from apps.agent_access.models import AgentAccessToken


class ExternalAgentDisabled(APIException):
    status_code = 503
    default_detail = {"code": "external_agent_disabled", "detail": "External Agent access is disabled."}
    default_code = "external_agent_disabled"


class ExternalAgentEnabled(BasePermission):
    def has_permission(self, request, view):
        if not settings.EXTERNAL_AGENT_ACCESS_ENABLED:
            raise ExternalAgentDisabled()
        return True


class HasTokenScopes(BasePermission):
    def has_permission(self, request, view):
        if not isinstance(request.auth, AgentAccessToken):
            return False
        required = set(getattr(view, "required_scopes", ()))
        granted = set(request.auth.scopes if isinstance(request.auth.scopes, list) else ())
        missing = sorted(required - granted)
        if missing:
            raise PermissionDenied({
                "code": "scope_denied",
                "detail": "The token does not grant the required scope.",
                "required_scopes": missing,
            })
        return True

