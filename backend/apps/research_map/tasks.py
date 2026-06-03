from __future__ import annotations

from celery import shared_task

from apps.library.models import KnowledgeSpace
from apps.research_map.services import generate_direction_map
from apps.tasks.models import TaskRecord


@shared_task(name="apps.research_map.tasks.generate_direction_map_task")
def generate_direction_map_task(root_space_id: int, task_id: int) -> dict[str, int]:
    task = TaskRecord.objects.get(pk=task_id)
    try:
        task.status = TaskRecord.Status.RUNNING
        task.stage = "generating"
        task.progress = 10
        task.save(update_fields=["status", "stage", "progress", "updated_at"])
        snapshot = generate_direction_map(KnowledgeSpace.objects.get(pk=root_space_id))
        task.status = TaskRecord.Status.SUCCESS
        task.stage = "completed"
        task.progress = 100
        task.result = {"snapshot_id": snapshot.id, "version": snapshot.version}
        task.save(update_fields=["status", "stage", "progress", "result", "updated_at"])
        return task.result
    except Exception as exc:
        task.status = TaskRecord.Status.FAILED
        task.stage = "failed"
        task.error = str(exc)
        task.save(update_fields=["status", "stage", "error", "updated_at"])
        raise
