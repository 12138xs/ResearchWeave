import hashlib
import json
from datetime import timedelta

from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import editable_by, visible_to
from apps.materials.models import Material, MaterialVersion, ResearchCard
from apps.materials.services import enqueue, ingest
from apps.storage.provider import get_storage_provider
from apps.tasks.models import TaskRecord


def materials(user, write=False):
    return (editable_by if write else visible_to)(Material.objects.all(), user)


def version_data(version):
    return {
        "id": version.pk, "number": version.number, "filename": version.filename,
        "format": version.format, "sha256": version.sha256, "size": version.size,
        "status": version.status, "error": version.error, "warnings": version.warnings,
        "parser_version": version.parser_version, "created_at": version.created_at,
        "file_url": f"/api/materials/{version.material_id}/versions/{version.pk}/file/",
    }


def material_data(material, user):
    return {
        "id": material.pk, "title": material.title, "visibility": material.visibility,
        "can_edit": material.owner_id == user.pk or (user.is_staff and material.visibility == "team"),
        "versions": [version_data(version) for version in material.versions.all()],
    }


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=500, required=False, default="", allow_blank=True)
    visibility = serializers.ChoiceField(choices=["team", "private"], default="team")


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


def get_version(user, pk, version_id, write=False, lock=False):
    allowed = materials(user, write=write).values("pk")
    queryset = MaterialVersion.objects.filter(material_id__in=allowed)
    if lock:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=version_id, material_id=pk)


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
        with transaction.atomic():
            version = get_version(request.user, pk, version_id, write=True, lock=True)
            if version.status in {"ready", "needs_review"}:
                return Response({"detail": "证据已生成，无需重复解析。"}, status=200)
            if version.status != "failed" and version.updated_at > timezone.now() - timedelta(minutes=5):
                return Response({"detail": "任务正在等待或执行，请稍后刷新。"}, status=409)
            version.status, version.error = "queued", ""
            version.save(update_fields=["status", "error", "updated_at"])
            TaskRecord.objects.filter(pk=version.task_id).update(status="pending", error="", stage="等待解析", updated_at=timezone.now())
            enqueue(version.pk)
        return Response({"detail": "已申请重新解析。"}, status=202)


class CardSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300)
    markdown = serializers.CharField(max_length=100_000)
    evidence_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)


class EvidenceReview(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, version_id, evidence_id):
        if request.data.get("confirmed") is not True:
            raise ValidationError("请明确确认已对照原文核对文字与公式。")
        with transaction.atomic():
            version = get_version(request.user, pk, version_id, write=True, lock=True)
            evidence = get_object_or_404(version.evidence, pk=evidence_id)
            if not evidence.text.strip():
                raise ValidationError("此页没有可用文字，不能标为已核对可用；请补充整理后的 Markdown 版本。")
            if evidence.reviewed_at is None:
                evidence.review_required = False
                evidence.reviewed_by = request.user
                evidence.reviewed_at = timezone.now()
                evidence.save(update_fields=["review_required", "reviewed_by", "reviewed_at"])
            if not version.evidence.filter(review_required=True).exists():
                version.status = "ready"
                version.save(update_fields=["status", "updated_at"])
        return Response({"detail": "已记录核对结果。"})


class CardImport(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, version_id):
        serializer = CardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        with transaction.atomic():
            version = get_version(request.user, pk, version_id, write=True, lock=True)
            ids = sorted(set(values["evidence_ids"]))
            if version.evidence.filter(pk__in=ids).count() != len(ids):
                raise ValidationError("研究卡片必须引用当前原文件版本的证据。")
            digest = hashlib.sha256(json.dumps([values["title"], values["markdown"], ids], ensure_ascii=False).encode()).hexdigest()
            card, created = ResearchCard.objects.get_or_create(version=version, sha256=digest,
                defaults={"title": values["title"], "markdown": values["markdown"], "created_by": request.user})
            if created:
                card.evidence.set(ids)
        return Response({"id": card.pk, "created": created, "kind": "derived"}, status=201 if created else 200)
