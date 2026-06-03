from __future__ import annotations

from django.db import transaction

from apps.library.models import Keyword
from apps.papers.models import Paper
from apps.storage.provider import get_storage_provider
from apps.tasks.models import TaskRecord


def delete_paper(paper: Paper) -> dict[str, object]:
    paper_id = paper.id
    source_pdf_path = paper.source_pdf_path
    keyword_ids = list(paper.keywords.values_list("id", flat=True))
    removed_related = {
        "light_profiles": paper.light_profiles.count(),
        "deep_profiles": paper.deep_profiles.count(),
        "qa_exchanges": paper.qa_exchanges.count(),
    }

    with transaction.atomic():
        locked_paper = Paper.objects.select_for_update().get(pk=paper_id)
        removed_tasks, _ = TaskRecord.objects.filter(object_type="paper", object_id=paper_id).delete()
        locked_paper.delete()
        removed_keywords = delete_orphan_keywords(keyword_ids)

    return {
        "deleted_id": paper_id,
        "removed_storage": delete_paper_storage(source_pdf_path),
        "removed_tasks": removed_tasks,
        "removed_related": removed_related,
        "removed_keywords": removed_keywords,
    }


def delete_orphan_keywords(keyword_ids: list[int]) -> list[str]:
    if not keyword_ids:
        return []
    orphan_keywords = list(
        Keyword.objects.filter(pk__in=keyword_ids, papers__isnull=True, documents__isnull=True)
        .distinct()
        .order_by("name")
    )
    removed_names = [keyword.name for keyword in orphan_keywords]
    if orphan_keywords:
        Keyword.objects.filter(pk__in=[keyword.pk for keyword in orphan_keywords]).delete()
    return removed_names


def delete_paper_storage(source_pdf_path: str) -> bool:
    if not source_pdf_path:
        return False
    try:
        path = get_storage_provider().resolve(source_pdf_path)
    except ValueError:
        return False
    if not path.exists() or not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True
