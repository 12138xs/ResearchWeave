from __future__ import annotations

from django.db import transaction

from apps.documents.selectors import document_index_projection
from apps.experiments.selectors import experiment_index_projection
from apps.papers.selectors import paper_index_projection
from apps.search.models import SearchIndexEntry
from apps.tasks.models import TaskRecord


def rebuild_search_index() -> dict[str, int]:
    projections = [
        *paper_index_projection(),
        *document_index_projection(),
        *experiment_index_projection(),
    ]
    with transaction.atomic():
        SearchIndexEntry.objects.all().delete()
        SearchIndexEntry.objects.bulk_create(
            [SearchIndexEntry(**projection) for projection in projections],
            batch_size=200,
        )
    return {"indexed": len(projections)}


def enqueue_search_reindex(user) -> TaskRecord:
    task = TaskRecord.objects.create(
        task_type="search_reindex",
        object_type="search",
        created_by=user if getattr(user, "is_authenticated", False) else None,
        stage="queued",
    )
    from apps.search.tasks import reindex_search_task

    try:
        reindex_search_task.delay(task.id)
    except Exception as exc:
        task.status = TaskRecord.Status.FAILED
        task.stage = "publish_failed"
        task.error = str(exc)
        task.save(update_fields=["status", "stage", "error", "updated_at"])
        raise
    return task
