from __future__ import annotations

from ipaddress import ip_address, ip_network

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_sameorigin
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.papers.light_processing import enqueue_light_processing
from apps.papers.metadata_completion import MetadataSuggestionUnavailable, suggest_paper_metadata
from apps.papers.models import Paper, ReadingReview
from apps.papers.reference_import import parse_reference_candidates
from apps.papers.serializers import (
    PaperDeepProfileSerializer,
    PaperMetadataUpdateSerializer,
    PaperReadingStateSerializer,
    PaperSerializer,
    PaperUploadSerializer,
    ReadingReviewSerializer,
)
from apps.papers.selectors import filtered_paper_queryset, paper_search_context
from apps.papers.services.delete import delete_paper
from apps.papers.services.deep import (
    DeepProcessingUnavailable,
    DeepTaskPublishError,
    activate_deep_profile,
    delete_deep_profile,
    enqueue_deep_profile_task,
)
from apps.papers.services.pdf import paper_download_filename, resolve_paper_pdf_path
from apps.papers.services.reading import (
    create_reading_review,
    get_or_create_reading_state,
    update_reading_review,
    update_reading_state,
)
from apps.papers.services.upload import (
    create_uploaded_paper,
)
from apps.tasks.models import TaskRecord
from apps.tasks.serializers import TaskRecordSerializer


class PaperQuerysetMixin:
    serializer_class = PaperSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return filtered_paper_queryset(self.request.query_params)


class PaperListView(PaperQuerysetMixin, ListAPIView):
    pass


class PaperSearchView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        context, missing_keywords = paper_search_context(request.query_params)
        if missing_keywords:
            return Response({"keywords": [f"只能选择已有关键词：{', '.join(missing_keywords)}"]}, status=400)
        return Response(
            {
                "count": context["count"],
                "page": context["page"],
                "page_size": context["page_size"],
                "total_pages": context["total_pages"],
                "results": PaperSerializer(
                    context["page_items"],
                    many=True,
                    context={"paper_display_numbers": context["paper_display_numbers"]},
                ).data,
                "related_keywords": context["related_keywords"],
                "hot_keywords": context["hot_keywords"],
                "years": context["years"],
            }
        )

class PaperDetailView(PaperQuerysetMixin, RetrieveUpdateAPIView):
    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT", "DELETE"}:
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_serializer_class(self):
        if self.request.method in {"PATCH", "PUT"}:
            return PaperMetadataUpdateSerializer
        return PaperSerializer

    def partial_update(self, request, *args, **kwargs):
        paper = self.get_object()
        serializer = self.get_serializer(paper, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        paper.refresh_from_db()
        return Response(PaperSerializer(paper).data)

    def delete(self, request, *args, **kwargs):
        paper = self.get_object()
        return Response(delete_paper(paper))


class PaperMetadataSuggestionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk: int):
        paper = get_object_or_404(Paper.objects.prefetch_related("keywords"), pk=pk)
        try:
            return Response(suggest_paper_metadata(paper))
        except MetadataSuggestionUnavailable as exc:
            return Response({"detail": str(exc)}, status=503)


class PaperReferenceImportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        content = request.data.get("content", "")
        candidates = parse_reference_candidates(str(content or ""))
        return Response({"count": len(candidates), "candidates": candidates})


class PaperReadingStateView(APIView):
    def get_permissions(self):
        if self.request.method in {"PATCH", "PUT"}:
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        return Response(PaperReadingStateSerializer(get_or_create_reading_state(paper)).data)

    def patch(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        state = get_or_create_reading_state(paper)
        serializer = PaperReadingStateSerializer(state, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = update_reading_state(paper, serializer.validated_data, user=request.user)
        return Response(PaperReadingStateSerializer(updated).data)


class PaperReadingReviewListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        reviews = paper.reading_reviews.all()
        return Response(ReadingReviewSerializer(reviews, many=True).data)

    def post(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        serializer = ReadingReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = create_reading_review(paper, serializer.validated_data, user=request.user)
        return Response(ReadingReviewSerializer(review).data, status=201)


class PaperReadingReviewDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk: int, review_id: int):
        review = get_object_or_404(ReadingReview, pk=review_id, paper_id=pk)
        serializer = ReadingReviewSerializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = update_reading_review(review, serializer.validated_data, user=request.user)
        return Response(ReadingReviewSerializer(updated).data)


class PaperUploadNetworkPermission(BasePermission):
    message = "Current network is not allowed to upload papers."

    def has_permission(self, request, view) -> bool:
        client_ip = _client_ip(request)
        try:
            parsed_ip = ip_address(client_ip)
        except ValueError:
            return False
        return any(
            parsed_ip in ip_network(cidr, strict=False)
            for cidr in settings.PAPER_UPLOAD_ALLOWED_CIDRS
        )


class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return


@method_decorator(csrf_exempt, name="dispatch")
class PaperUploadView(APIView):
    permission_classes = [IsAuthenticated, PaperUploadNetworkPermission]
    authentication_classes = [CsrfExemptSessionAuthentication]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = PaperUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        paper, storage_key, post_upload_task = create_uploaded_paper(upload, serializer.validated_data)
        payload = PaperSerializer(paper).data
        payload["source_pdf_path"] = storage_key
        payload["post_upload_task"] = TaskRecordSerializer(post_upload_task).data
        return Response(payload, status=201)


@method_decorator(csrf_exempt, name="dispatch")
class PaperLightProcessView(APIView):
    permission_classes = [IsAuthenticated, PaperUploadNetworkPermission]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        use_ai = _truthy(request.data.get("use_ai")) or _truthy(request.query_params.get("use_ai"))
        task = enqueue_light_processing(paper, use_ai=use_ai)
        paper.refresh_from_db()
        return Response(
            {
                "paper": PaperSerializer(paper).data,
                "task": TaskRecordSerializer(task).data,
            },
            status=202,
        )


@method_decorator(csrf_exempt, name="dispatch")
class PaperDeepProcessView(APIView):
    permission_classes = [IsAuthenticated, PaperUploadNetworkPermission]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        guidance = str(request.data.get("guidance") or request.data.get("deep_guidance") or "").strip()
        try:
            task = enqueue_deep_profile_task(paper, guidance=guidance)
        except DeepProcessingUnavailable as exc:
            return Response({"detail": str(exc)}, status=400)
        except DeepTaskPublishError as exc:
            return Response({"detail": str(exc)}, status=503)
        paper.refresh_from_db()
        return Response(
            {
                "paper": PaperSerializer(paper).data,
                "task": TaskRecordSerializer(task).data,
            },
            status=202,
        )


class PaperDeepProfileListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        profiles = list(paper.deep_profiles.all())
        active = next((profile for profile in profiles if profile.is_active), None)
        return Response(
            {
                "active": PaperDeepProfileSerializer(active).data if active else None,
                "results": PaperDeepProfileSerializer(profiles, many=True).data,
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class PaperDeepProfileActivateView(APIView):
    permission_classes = [IsAuthenticated, PaperUploadNetworkPermission]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def post(self, request, pk: int, profile_id: int):
        paper = get_object_or_404(Paper, pk=pk)
        target, profiles, annotation_validation = activate_deep_profile(paper, profile_id=profile_id)
        return Response(
            {
                "active": PaperDeepProfileSerializer(target).data,
                "results": PaperDeepProfileSerializer(profiles, many=True).data,
                "annotation_validation": annotation_validation,
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class PaperDeepProfileDeleteView(APIView):
    permission_classes = [IsAuthenticated, PaperUploadNetworkPermission]
    authentication_classes = [CsrfExemptSessionAuthentication]

    def delete(self, request, pk: int, profile_id: int):
        paper = get_object_or_404(Paper, pk=pk)
        active, profiles = delete_deep_profile(paper, profile_id=profile_id)
        return Response(
            {
                "active": PaperDeepProfileSerializer(active).data if active else None,
                "results": PaperDeepProfileSerializer(profiles, many=True).data,
            }
        )


@method_decorator(xframe_options_sameorigin, name="dispatch")
class PaperPdfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        path = resolve_paper_pdf_path(paper)
        if path is None:
            raise Http404("Paper PDF is not available.")
        as_attachment = request.query_params.get("download") in {"1", "true", "yes"}
        return FileResponse(
            path.open("rb"),
            as_attachment=as_attachment,
            filename=paper_download_filename(paper),
            content_type="application/pdf",
        )


def _client_ip(request) -> str:
    remote_ip = request.META.get("REMOTE_ADDR", "").strip()
    if _ip_in_cidrs(remote_ip, settings.PAPER_TRUSTED_PROXY_CIDRS):
        real_ip = request.META.get("HTTP_X_REAL_IP", "").strip()
        if real_ip:
            return real_ip
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        for item in forwarded_for.split(","):
            forwarded_ip = item.strip()
            if forwarded_ip:
                return forwarded_ip
        forwarded = request.META.get("HTTP_X_FORWARDED", "").strip()
        if forwarded:
            return forwarded
    return remote_ip


def _ip_in_cidrs(value: str, cidrs: list[str]) -> bool:
    try:
        parsed_ip = ip_address(value)
    except ValueError:
        return False
    return any(parsed_ip in ip_network(cidr, strict=False) for cidr in cidrs)


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
