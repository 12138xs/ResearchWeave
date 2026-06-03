from __future__ import annotations

from apps.documents.models import Document
from apps.papers.models import Paper
from apps.quality.models import QualityIssue
from apps.tasks.models import TaskRecord


def run_quality_audit(task: TaskRecord | None = None) -> dict[str, int]:
    created = 0
    for paper in Paper.objects.prefetch_related("keywords"):
        if not paper.abstract.strip():
            _, was_created = QualityIssue.objects.update_or_create(
                object_type="paper",
                object_id=paper.id,
                dimension=QualityIssue.Dimension.METADATA,
                status=QualityIssue.Status.OPEN,
                defaults={
                    "severity": QualityIssue.Severity.MEDIUM,
                    "score": 45,
                    "notes": "论文缺少摘要，建议补充后再进入深读或复现。",
                    "evidence_json": {"field": "abstract"},
                    "source_task": task,
                },
            )
            created += int(was_created)
        if not paper.keywords.exists():
            _, was_created = QualityIssue.objects.update_or_create(
                object_type="paper",
                object_id=paper.id,
                dimension=QualityIssue.Dimension.METADATA,
                status=QualityIssue.Status.OPEN,
                defaults={
                    "severity": QualityIssue.Severity.LOW,
                    "score": 60,
                    "notes": "论文尚未设置关键词，会影响检索和方向聚合。",
                    "evidence_json": {"field": "keywords"},
                    "source_task": task,
                },
            )
            created += int(was_created)
    for document in Document.objects.all():
        if not document.summary.strip():
            _, was_created = QualityIssue.objects.update_or_create(
                object_type="document",
                object_id=document.id,
                dimension=QualityIssue.Dimension.DOCUMENT,
                status=QualityIssue.Status.OPEN,
                defaults={
                    "severity": QualityIssue.Severity.LOW,
                    "score": 65,
                    "notes": "文档缺少摘要，列表和搜索结果不容易判断内容。",
                    "evidence_json": {"field": "summary"},
                    "source_task": task,
                },
            )
            created += int(was_created)
    return {"created_or_reopened": created}


def enqueue_quality_audit(user) -> TaskRecord:
    task = TaskRecord.objects.create(
        task_type="quality_audit",
        object_type="quality",
        created_by=user if getattr(user, "is_authenticated", False) else None,
        stage="queued",
    )
    from apps.quality.tasks import run_quality_audit_task

    try:
        run_quality_audit_task.delay(task.id)
    except Exception as exc:
        task.status = TaskRecord.Status.FAILED
        task.stage = "publish_failed"
        task.error = str(exc)
        task.save(update_fields=["status", "stage", "error", "updated_at"])
        raise
    return task
