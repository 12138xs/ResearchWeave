from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.materials.services import enqueue, ingest, import_card, retry_version, review_evidence
from apps.materials.selectors import materials, get_version, version_data, material_data
from apps.materials.serializers import UploadSerializer, CardSerializer
from apps.storage.provider import get_storage_provider


def upload_response(request, material=None):
    serializer = UploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    version, created = ingest(values["file"], owner=request.user, title=values["title"],
                              visibility=material.visibility if material else values["visibility"], material=material)
    if created:
        enqueue(version.pk)
    version.refresh_from_db()
    return Response({"material_id": version.material_id, "created": created, "version": version_data(version)}, status=201 if created else 200)


class MaterialList(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = materials(request.user).prefetch_related("versions")
        query = str(request.query_params.get("q", ""))[:200].strip()
        if query:
            queryset = queryset.filter(title__icontains=query)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except ValueError:
            raise ValidationError("页码无效。")
        return Response({"count": queryset.count(), "page": page,
                         "results": [material_data(row, request.user) for row in queryset[(page - 1) * 25:page * 25]]})

    def post(self, request):
        return upload_response(request)


class MaterialDetail(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        return Response(material_data(get_object_or_404(materials(request.user).prefetch_related("versions"), pk=pk), request.user))


class VersionUpload(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        return upload_response(request, get_object_or_404(materials(request.user, write=True), pk=pk))


class VersionDetail(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, version_id):
        version = get_version(request.user, pk, version_id)
        data = version_data(version)
        data["evidence"] = list(version.evidence.values("id", "ordinal", "page", "line_start", "line_end", "text", "review_required", "reviewed_at"))
        data["cards"] = [{"id": card.pk, "title": card.title, "markdown": card.markdown,
                          "evidence_ids": [row.pk for row in card.evidence.all()], "kind": "derived"}
                         for card in version.cards.prefetch_related("evidence").order_by("id")]
        return Response(data)


class VersionFile(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, version_id):
        version = get_version(request.user, pk, version_id)
        path = get_storage_provider().resolve(version.storage_key)
        if not path.is_file():
            raise Http404("原文件暂不可用。")
        response = FileResponse(path.open("rb"), filename=version.filename,
                                content_type="application/pdf" if version.format == "pdf" else "text/plain; charset=utf-8")
        response["X-Content-Type-Options"] = "nosniff"
        # Uploaded active content is never allowed to execute under the application origin.
        response["Content-Security-Policy"] = "sandbox"
        return response


class VersionRetry(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, version_id):
        status, message = retry_version(request.user, pk, version_id)
        return Response({"detail": message}, status=status)


class EvidenceReview(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, version_id, evidence_id):
        review_evidence(request.user, pk, version_id, evidence_id, request.data.get("confirmed"))
        return Response({"detail": "已记录核对结果。"})


class CardImport(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, version_id):
        serializer = CardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        card, created = import_card(request.user, pk, version_id, values)
        return Response({"id": card.pk, "created": created, "kind": "derived"}, status=201 if created else 200)
