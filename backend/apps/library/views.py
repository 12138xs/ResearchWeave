from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import ReadOnlyOrAuthenticatedWriteMixin
from apps.library.models import KnowledgeSpace
from apps.library.selectors import (
    catalog_stats_payload,
    keyword_library_payload,
    keyword_summary_entries,
)
from apps.library.serializers import KeywordLibraryEntrySerializer, KnowledgeSpaceSerializer
from apps.library.services.spaces import (
    KnowledgeSpaceMoveError,
    archive_knowledge_space,
    move_knowledge_space,
)


class KnowledgeSpaceListView(ReadOnlyOrAuthenticatedWriteMixin, ListCreateAPIView):
    serializer_class = KnowledgeSpaceSerializer

    def get_queryset(self):
        queryset = KnowledgeSpace.objects.filter(is_active=True).select_related("parent")
        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["active_spaces"] = list(
            KnowledgeSpace.objects.filter(is_active=True).select_related("parent")
        )
        return context


class KnowledgeSpaceDetailView(ReadOnlyOrAuthenticatedWriteMixin, RetrieveUpdateAPIView):
    serializer_class = KnowledgeSpaceSerializer

    def get_queryset(self):
        return KnowledgeSpace.objects.filter(is_active=True).select_related("parent")


class KnowledgeSpaceMoveView(ReadOnlyOrAuthenticatedWriteMixin, APIView):

    def post(self, request, pk: int):
        space = get_object_or_404(KnowledgeSpace, pk=pk, is_active=True)
        parent_provided = "parent_id" in request.data
        parent_id = None
        if "parent_id" in request.data:
            parent_id = _parse_parent_id(request.data.get("parent_id"))
            if parent_id is _INVALID_PARENT_ID:
                return Response(
                    {"detail": "parent_id must be null or a non-negative integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        order_provided = "order" in request.data
        order = None
        if "order" in request.data:
            order = _parse_non_negative_order(request.data["order"])
            if order is None:
                return Response(
                    {"detail": "order must be a non-negative integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            space = move_knowledge_space(
                space=space,
                parent_id=parent_id,
                order=order,
                parent_provided=parent_provided,
                order_provided=order_provided,
            )
        except KnowledgeSpaceMoveError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(KnowledgeSpaceSerializer(space).data)


class KnowledgeSpaceArchiveView(ReadOnlyOrAuthenticatedWriteMixin, APIView):

    def post(self, request, pk: int):
        space = get_object_or_404(KnowledgeSpace, pk=pk, is_active=True)
        return Response(KnowledgeSpaceSerializer(archive_knowledge_space(space)).data)


class CatalogStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(catalog_stats_payload())


class KeywordLibraryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = KeywordLibraryEntrySerializer(keyword_library_payload(), many=True)
        return Response(serializer.data)


class KeywordSuggestView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip().lower()
        limit = _positive_int(request.query_params.get("limit"), default=10, maximum=30)
        return Response(keyword_summary_entries(limit=limit, query=query))


def _positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


def _parse_non_negative_order(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


_INVALID_PARENT_ID = object()


def _parse_parent_id(value: object) -> int | None | object:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return _INVALID_PARENT_ID
    if isinstance(value, int):
        return value if value >= 0 else _INVALID_PARENT_ID
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return _INVALID_PARENT_ID
