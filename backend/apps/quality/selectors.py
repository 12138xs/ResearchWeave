from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.documents.selectors import document_queryset
from apps.papers.selectors import filtered_paper_queryset
from apps.quality.models import QualityIssue
from apps.experiments.selectors import accessible_experiments


def quality_issue_queryset(params, *, user=None, write=False) -> QuerySet[QualityIssue]:
    queryset = QualityIssue.objects.select_related("source_task", "reviewed_by")
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    # Paper/Document 原生读写均为成员共享；实验仍按原生读写权限分离。
    # 精确类型与存在的目标同时求交，未知类型和孤儿没有放行分支。
    queryset = queryset.filter(
        Q(object_type="paper", object_id__in=filtered_paper_queryset({}).values("pk"))
        | Q(object_type="document", object_id__in=document_queryset({}, for_list=False).values("pk"))
        | Q(object_type="experiment", object_id__in=accessible_experiments(user, write=write).values("pk"))
    )
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
