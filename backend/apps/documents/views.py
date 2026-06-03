from __future__ import annotations

from math import ceil

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import ReadOnlyOrAuthenticatedWriteMixin
from apps.documents.importing import approve_candidate
from apps.documents.models import DocumentImportBatch, DocumentImportCandidate
from apps.documents.selectors import (
    document_import_batch_queryset,
    document_import_candidate_queryset,
    document_queryset,
    parse_space_id,
)
from apps.documents.serializers import (
    DocumentImportBatchSerializer,
    DocumentImportCandidateSerializer,
    DocumentListSerializer,
    DocumentSerializer,
)
from apps.documents.tasks import generate_document_import_candidates


class DocumentQuerysetMixin(ReadOnlyOrAuthenticatedWriteMixin):
    serializer_class = DocumentSerializer

    def parse_space_id(self, value: str) -> int | None:
        return parse_space_id(value)

    def get_queryset(self):
        return document_queryset(
            self.request.query_params,
            for_list=isinstance(self, DocumentListView),
        )


class DocumentListView(DocumentQuerysetMixin, ListCreateAPIView):
    default_page_size = 25
    max_page_size = 100

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        count = queryset.count()
        page = _positive_int(request.query_params.get("page"), default=1)
        page_size = _positive_int(
            request.query_params.get("page_size"),
            default=self.default_page_size,
            maximum=self.max_page_size,
        )
        total_pages = max(1, ceil(count / page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size
        serializer = DocumentListSerializer(queryset[offset : offset + page_size], many=True)
        return Response(
            {
                "count": count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "results": serializer.data,
            }
        )


class DocumentDetailView(DocumentQuerysetMixin, RetrieveUpdateAPIView):
    pass


class DocumentImportBatchListView(ReadOnlyOrAuthenticatedWriteMixin, ListCreateAPIView):
    serializer_class = DocumentImportBatchSerializer

    def get_queryset(self):
        return document_import_batch_queryset()


class DocumentImportBatchDetailView(ReadOnlyOrAuthenticatedWriteMixin, RetrieveUpdateAPIView):
    serializer_class = DocumentImportBatchSerializer

    def get_queryset(self):
        return document_import_batch_queryset()


class DocumentImportBatchEnqueueView(ReadOnlyOrAuthenticatedWriteMixin, APIView):

    def post(self, request, pk: int):
        batch = get_object_or_404(DocumentImportBatch, pk=pk)
        batch.status = DocumentImportBatch.Status.QUEUED
        batch.error_message = ""
        batch.save(update_fields=["status", "error_message", "updated_at"])
        generate_document_import_candidates.delay(batch.id)
        return Response(DocumentImportBatchSerializer(batch).data)


class DocumentImportCandidateListView(ReadOnlyOrAuthenticatedWriteMixin, ListCreateAPIView):
    serializer_class = DocumentImportCandidateSerializer

    def parse_batch_id(self, value: str) -> int | None:
        if not value.isdigit() or len(value) > 18:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed <= 0:
            return None
        return parsed

    def get_queryset(self):
        queryset = document_import_candidate_queryset()
        batch_id = self.request.query_params.get("batch_id")
        if batch_id is not None:
            parsed_batch_id = self.parse_batch_id(batch_id.strip())
            if parsed_batch_id is None:
                return queryset.none()
            queryset = queryset.filter(batch_id=parsed_batch_id)
        return queryset


class DocumentImportCandidateDetailView(ReadOnlyOrAuthenticatedWriteMixin, RetrieveUpdateAPIView):
    serializer_class = DocumentImportCandidateSerializer

    def get_queryset(self):
        return document_import_candidate_queryset()


class DocumentImportCandidateApproveView(ReadOnlyOrAuthenticatedWriteMixin, APIView):

    def post(self, request, pk: int):
        candidate = get_object_or_404(DocumentImportCandidate, pk=pk)
        reviewer = request.user if request.user.is_authenticated else None
        try:
            document = approve_candidate(candidate, reviewer=reviewer)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DocumentSerializer(document).data)


def _positive_int(value: object, *, default: int, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    if maximum is not None:
        return min(parsed, maximum)
    return parsed
