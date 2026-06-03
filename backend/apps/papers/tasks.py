from __future__ import annotations

from celery import shared_task

from apps.papers.deep_processing import run_deep_processing_with_task
from apps.papers.light_processing import run_light_processing_with_task
from apps.papers.models import Paper
from apps.papers.post_upload import run_upload_postprocess_with_task
from apps.tasks.models import TaskRecord


@shared_task(name="apps.papers.tasks.run_paper_light_process_task")
def run_paper_light_process_task(paper_id: int, task_id: int, use_ai: bool = False) -> dict[str, object]:
    paper = Paper.objects.get(pk=paper_id)
    task = TaskRecord.objects.get(pk=task_id)
    result = run_light_processing_with_task(paper, task=task, use_ai=use_ai)
    return {
        "paper_id": result.paper.id,
        "profile_id": result.profile.id,
        **result.task.result,
    }


@shared_task(name="apps.papers.tasks.run_paper_upload_postprocess_task", soft_time_limit=360, time_limit=420)
def run_paper_upload_postprocess_task(paper_id: int, task_id: int) -> dict[str, object]:
    paper = Paper.objects.get(pk=paper_id)
    task = TaskRecord.objects.get(pk=task_id)
    result = run_upload_postprocess_with_task(paper, task=task)
    return {
        "paper_id": paper.id,
        **result.result,
    }


@shared_task(name="apps.papers.tasks.run_paper_deep_process_task", soft_time_limit=2400, time_limit=2700)
def run_paper_deep_process_task(paper_id: int, task_id: int) -> dict[str, object]:
    paper = Paper.objects.get(pk=paper_id)
    task = TaskRecord.objects.get(pk=task_id)
    result = run_deep_processing_with_task(paper, task=task)
    return {
        "paper_id": result.paper.id,
        "deep_profile_id": result.profile.id,
        **result.task.result,
    }
