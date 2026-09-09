"""Immutable originals and evidence; no model or external API is called here."""
import hashlib
from pathlib import Path
from uuid import uuid4

from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone
from pypdf import PdfReader
from rest_framework.exceptions import ValidationError

from apps.common.permissions import Visibility, editable_by
from apps.materials.models import Evidence, Material, MaterialVersion
from apps.storage.provider import get_storage_provider
from apps.tasks.models import TaskRecord

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 500
MAX_TEXT = 4_000_000
PARSER_VERSION = "pypdf6-markdown-lines-v1"


def ingest(upload, *, owner, title="", visibility="team", material=None):
    suffix = Path(upload.name).suffix.lower()
    if suffix not in {".pdf", ".md", ".markdown"}:
        raise ValidationError("只支持 PDF 和 UTF-8 Markdown 文件。")
    if not upload.size or upload.size > MAX_BYTES:
        raise ValidationError("文件不能为空，且不能超过 25 MB。")
    if visibility not in Visibility.values:
        raise ValidationError("可见范围无效。")
    data = upload.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValidationError("文件不能超过 25 MB。")
    digest = hashlib.sha256(data).hexdigest()
    target = None
    try:
        with transaction.atomic():
            # Serialize identical uploads, including concurrent first uploads without a material row.
            scope = f"{visibility}:{owner.pk if visibility == 'private' else 0}:{digest}"
            lock = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
            if material is not None:
                material = editable_by(Material.objects.select_for_update(), owner).get(pk=material.pk)
                duplicate = material.versions.filter(sha256=digest).first()
            else:
                duplicates = MaterialVersion.objects.filter(sha256=digest, material__visibility=visibility)
                if visibility == Visibility.PRIVATE:
                    duplicates = duplicates.filter(material__owner=owner)
                duplicate = duplicates.order_by("id").first()
            if duplicate:
                return duplicate, False
            if material is None:
                material = Material.objects.create(title=(title.strip() or Path(upload.name).stem)[:500], owner=owner, visibility=visibility)
            number = (material.versions.aggregate(n=Max("number"))["n"] or 0) + 1
            storage_key = f"objects/materials/{uuid4().hex}{'.pdf' if suffix == '.pdf' else '.md'}"
            target = get_storage_provider().resolve(storage_key)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(data)
            version = MaterialVersion.objects.create(
                material=material, number=number, sha256=digest, filename=Path(upload.name).name[:255],
                format="pdf" if suffix == ".pdf" else "md", storage_key=storage_key, size=len(data), created_by=owner,
            )
            version.task = TaskRecord.objects.create(task_type="material_parse", object_type="material_version", object_id=version.pk, created_by=owner)
            version.save(update_fields=["task"])
        return version, True
    except Exception:
        if target:
            target.unlink(missing_ok=True)
        raise


def enqueue(version_id):
    from apps.materials.tasks import parse_material

    def publish():
        try:
            parse_material.apply_async(args=[version_id], queue="heavy_q", retry=False)
        except Exception:
            with transaction.atomic():
                version = MaterialVersion.objects.select_for_update().get(pk=version_id)
                if version.status == "queued":
                    fail(version, "解析队列暂不可用，原文件已保存，请稍后重试。")
    transaction.on_commit(publish)


def fail(version, message):
    version.status = "failed"
    version.error = message
    version.save(update_fields=["status", "error", "updated_at"])
    TaskRecord.objects.filter(pk=version.task_id).update(status="failed", error=message, stage="解析失败", updated_at=timezone.now())


def _extract(version):
    path = get_storage_provider().resolve(version.storage_key)
    if hashlib.sha256(path.read_bytes()).hexdigest() != version.sha256:
        raise ValueError("original hash mismatch")
    rows, warnings = [], []
    if version.format == "md":
        text = path.read_text(encoding="utf-8-sig")
        if "\x00" in text or len(text) > MAX_TEXT:
            raise ValueError("invalid markdown")
        lines = text.splitlines()
        for start in range(0, len(lines), 60):
            part = "\n".join(lines[start:start + 60])
            review = "\ufffd" in part
            rows.append(Evidence(version=version, ordinal=len(rows) + 1, line_start=start + 1,
                                 line_end=min(start + 60, len(lines)), text=part, review_required=review))
        if any(row.review_required for row in rows):
            warnings.append("文本含替换字符，请对照原文件核对。")
        if not text.strip():
            warnings.append("文件未包含可用正文。")
    else:
        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
            raise ValueError("encrypted or oversized PDF")
        total = 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_TEXT:
                raise ValueError("text limit")
            rows.append(Evidence(version=version, ordinal=number, page=number, text=text, review_required=True))
        warnings.append("PDF 文本已按物理页码提取；公式、图表和阅读顺序尚未经人工核对。请以原文件为准。")
        if any(not row.text.strip() for row in rows):
            warnings.append("部分页面没有可提取文字，可能是扫描页；原页仍保留，不会自动生成缺失内容。")
    if not rows:
        warnings.append("没有提取到证据，需检查原文件。")
    return rows, warnings


def parse_version(version_id):
    # One transaction per bounded document: duplicate delivery cannot duplicate evidence.
    # If the worker dies, PostgreSQL rolls back; stale queued tasks can be retried.
    with transaction.atomic():
        version = MaterialVersion.objects.select_for_update().get(pk=version_id)
        if version.status in {"ready", "needs_review"}:
            return
        TaskRecord.objects.filter(pk=version.task_id).update(status="running", stage="提取证据", updated_at=timezone.now())
        try:
            rows, warnings = _extract(version)
        except Exception:
            fail(version, "未能完整解析。请检查文件是否损坏、加密、采用 UTF-8 编码，或超过 500 页及文本上限；原文件仍可下载。")
            return
        Evidence.objects.bulk_create(rows)
        version.status = "needs_review" if warnings else "ready"
        version.warnings = warnings
        version.error = ""
        version.parser_version = PARSER_VERSION
        version.save(update_fields=["status", "warnings", "error", "parser_version", "updated_at"])
        TaskRecord.objects.filter(pk=version.task_id).update(
            status="success", progress=100, stage="证据已保存", error="",
            result={"material_id": version.material_id, "version_id": version.pk, "evidence_count": len(rows), "status": version.status},
            updated_at=timezone.now(),
        )
