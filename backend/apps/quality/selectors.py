from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.quality.models import QualityIssue
from apps.experiments.selectors import accessible_experiments


def quality_issue_queryset(params, *, user=None, write=False) -> QuerySet[QualityIssue]:
    queryset = QualityIssue.objects.select_related("source_task", "reviewed_by")
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    queryset = queryset.filter(~Q(object_type="experiment") | Q(
        object_id__in=accessible_experiments(user, write=write).values("id")))
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
