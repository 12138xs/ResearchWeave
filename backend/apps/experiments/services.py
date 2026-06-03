from __future__ import annotations

from django.utils import timezone

from apps.experiments.models import ExperimentRun
from apps.tasks.models import TaskRecord


def create_experiment_run(project, data: dict, *, user) -> ExperimentRun:
    return ExperimentRun.objects.create(
        project=project,
        status=data.get("status", ExperimentRun.Status.PLANNED),
        params_json=data.get("params_json", {}),
        metrics_json=data.get("metrics_json", {}),
        artifact_keys=data.get("artifact_keys", []),
        notes=data.get("notes", ""),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def enqueue_experiment_run(run: ExperimentRun, *, user) -> TaskRecord:
    task = TaskRecord.objects.create(
        task_type="experiment_run_execute",
        status=TaskRecord.Status.PENDING,
        progress=0,
        stage="queued",
        object_type="experiment_run",
        object_id=run.id,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    run.status = ExperimentRun.Status.RUNNING
    run.started_at = run.started_at or timezone.now()
    run.save(update_fields=["status", "started_at", "updated_at"])
    from apps.experiments.tasks import run_experiment_task

    try:
        run_experiment_task.delay(run.id, task.id)
    except Exception as exc:
        task.status = TaskRecord.Status.FAILED
        task.stage = "publish_failed"
        task.error = str(exc)
        task.save(update_fields=["status", "stage", "error", "updated_at"])
        run.status = ExperimentRun.Status.FAILED
        run.save(update_fields=["status", "updated_at"])
        raise
    return task


def complete_experiment_run(run: ExperimentRun, task: TaskRecord) -> dict:
    run.status = ExperimentRun.Status.SUCCESS
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at", "updated_at"])
    task.status = TaskRecord.Status.SUCCESS
    task.progress = 100
    task.stage = "completed"
    task.result = {"run_id": run.id, "project_id": run.project_id}
    task.error = ""
    task.save(update_fields=["status", "progress", "stage", "result", "error", "updated_at"])
    return task.result
