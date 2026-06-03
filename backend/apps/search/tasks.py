from __future__ import annotations

from celery import shared_task

from apps.search.services import rebuild_search_index
from apps.tasks.models import TaskRecord


@shared_task(name="apps.search.tasks.reindex_search_task")
def reindex_search_task(task_id: int) -> dict[str, int]:
    task = TaskRecord.objects.get(pk=task_id)
    try:
        task.status = TaskRecord.Status.RUNNING
        task.stage = "indexing"
        task.progress = 10
        task.save(update_fields=["status", "stage", "progress", "updated_at"])
        result = rebuild_search_index()
        task.status = TaskRecord.Status.SUCCESS
        task.stage = "completed"
        task.progress = 100
        task.result = result
        task.save(update_fields=["status", "stage", "progress", "result", "updated_at"])
        return result
    except Exception as exc:
        task.status = TaskRecord.Status.FAILED
        task.stage = "failed"
        task.error = str(exc)
        task.save(update_fields=["status", "stage", "error", "updated_at"])
        raise
