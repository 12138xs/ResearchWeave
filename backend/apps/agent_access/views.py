from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agent_access.audit import AuditedAgentAPIViewMixin, record_control_plane_event
from apps.agent_access.authentication import PersonalAccessTokenAuthentication
from apps.agent_access.contracts import material_evidence_reference
from apps.agent_access.models import AgentAccessToken
from apps.agent_access.permissions import ExternalAgentEnabled, HasTokenScopes
from apps.agent_access.serializers import EvidenceSearchSerializer, ExternalAccessUpdateSerializer, TokenIssueSerializer
from apps.materials.selectors import externally_accessible_materials
from apps.materials.services import set_external_agent_access
from apps.search.evidence import search_evidence


def token_data(token):
    return {
        "token_id": str(token.token_id),
        "name": token.name,
        "scopes": token.scopes,
        "expires_at": token.expires_at,
        "revoked_at": token.revoked_at,
        "last_used_at": token.last_used_at,
        "created_at": token.created_at,
    }


def agent_material_data(material):
    versions = list(material.versions.all())
    latest = versions[0] if versions else None
    return {
        "material_id": material.pk,
        "title": material.title,
        "source_kind": material.source_kind,
        "visibility": material.visibility,
        "latest_version": None if latest is None else {
            "version_id": latest.pk,
            "version_number": latest.number,
            "status": latest.status,
            "filename": latest.filename,
            "sha256": latest.sha256,
            "created_at": latest.created_at,
        },
    }


class SecureSessionAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        if not request.is_secure():
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied({"code": "insecure_transport", "detail": "This operation requires HTTPS."})
        super().initial(request, *args, **kwargs)


class TokenListCreateView(SecureSessionAPIView):
    def get(self, request):
        return Response({"results": [token_data(row) for row in request.user.agent_access_tokens.all()]})

    def post(self, request):
        serializer = TokenIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        token, raw = AgentAccessToken.issue(owner=request.user, **values)
        response = Response({**token_data(token), "token": raw}, status=201)
        return record_control_plane_event(request, action="token.create", response=response, token=token)


class TokenRevokeView(SecureSessionAPIView):
    def delete(self, request, token_id):
        token = get_object_or_404(request.user.agent_access_tokens, token_id=token_id)
        token.revoke()
        return record_control_plane_event(request, action="token.revoke", response=Response(status=204), token=token)


class MaterialExternalAccessView(SecureSessionAPIView):
    def patch(self, request, pk):
        serializer = ExternalAccessUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        material = set_external_agent_access(request.user, pk, **serializer.validated_data)
        response = Response({
            "material_id": material.pk,
            "source_kind": material.source_kind,
            "external_agent_access": material.external_agent_access,
            "changed_at": material.external_access_changed_at,
        })
        return record_control_plane_event(request, action="material.external_access.update", response=response)


class AgentReadAPIView(AuditedAgentAPIViewMixin, APIView):
    authentication_classes = [PersonalAccessTokenAuthentication]
    permission_classes = [ExternalAgentEnabled, IsAuthenticated, HasTokenScopes]
    required_scopes = ()


class AgentMeView(AgentReadAPIView):
    audit_action = "me.read"

    def get(self, request):
        scopes = sorted(set(request.auth.scopes))
        capabilities = []
        if "materials:read" in scopes:
            capabilities.extend(["materials.list", "materials.get"])
        if "evidence:read" in scopes:
            capabilities.append("evidence.search")
        return Response({
            "user_id": request.user.pk,
            "token_id": str(request.auth.token_id),
            "scopes": scopes,
            "capabilities": capabilities,
        })


class AgentMaterialListView(AgentReadAPIView):
    audit_action = "materials.list"
    required_scopes = ("materials:read",)

    def get(self, request):
        queryset = externally_accessible_materials(request.user).prefetch_related("versions")
        query = str(request.query_params.get("q", ""))[:200].strip()
        if query:
            queryset = queryset.filter(title__icontains=query)
        rows = list(queryset[:50])
        return Response({
            "count": len(rows),
            "truncated": queryset.count() > len(rows),
            "next_cursor": None,
            "warnings": [],
            "results": [agent_material_data(row) for row in rows],
        })


class AgentMaterialDetailView(AgentReadAPIView):
    audit_action = "materials.get"
    required_scopes = ("materials:read",)

    def get(self, request, pk):
        material = get_object_or_404(
            externally_accessible_materials(request.user).prefetch_related("versions"),
            pk=pk,
        )
        return Response(agent_material_data(material))


class AgentEvidenceSearchView(AgentReadAPIView):
    audit_action = "evidence.search"
    required_scopes = ("evidence:read",)

    def post(self, request):
        serializer = EvidenceSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allowed = externally_accessible_materials(request.user)
        payload = search_evidence(
            request.user,
            serializer.validated_data,
            allowed_materials=allowed,
            include_evidence_objects=True,
        )
        for row in payload["results"]:
            row["source"] = material_evidence_reference(row.pop("_evidence"))
            row.pop("file_url", None)
            row.pop("url", None)
        payload["notice"] = "Results use the current bounded keyword retrieval baseline."
        payload.update({"truncated": payload.pop("candidate_limit_reached"), "next_cursor": None, "warnings": []})
        return Response(payload)
