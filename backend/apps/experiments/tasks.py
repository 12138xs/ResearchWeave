from __future__ import annotations

from celery import shared_task

from apps.experiments.models import ExperimentRun
from apps.experiments.services import complete_experiment_run
from apps.tasks.models import TaskRecord


@shared_task(name="apps.experiments.tasks.run_experiment_task")
def run_experiment_task(run_id: int, task_id: int) -> dict:
    task = TaskRecord.objects.get(pk=task_id)
    try:
        task.status = TaskRecord.Status.RUNNING
        task.progress = 25
        task.stage = "checking"
        task.save(update_fields=["status", "progress", "stage", "updated_at"])
        run = ExperimentRun.objects.select_related("project").get(pk=run_id)
        return complete_experiment_run(run, task)
    except Exception as exc:
        run = ExperimentRun.objects.filter(pk=run_id).first()
        if run is not None:
            run.status = ExperimentRun.Status.FAILED
            run.save(update_fields=["status", "updated_at"])
        task.status = TaskRecord.Status.FAILED
        task.error = str(exc)
        task.stage = "failed"
        task.save(update_fields=["status", "error", "stage", "updated_at"])
        raise
