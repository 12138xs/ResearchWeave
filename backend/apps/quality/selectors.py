from __future__ import annotations

from django.db.models import QuerySet

from apps.quality.models import QualityIssue


def quality_issue_queryset(params) -> QuerySet[QualityIssue]:
    queryset = QualityIssue.objects.select_related("source_task", "reviewed_by")
    object_type = params.get("object_type", "").strip()
    object_id = params.get("object_id", "").strip()
    status = params.get("status", "").strip()

    if object_type:
        queryset = queryset.filter(object_type=object_type)
    if object_id.isdigit():
        queryset = queryset.filter(object_id=int(object_id))
    if status:
        queryset = queryset.filter(status=status)
    return queryset.order_by("status", "-severity", "-updated_at")
