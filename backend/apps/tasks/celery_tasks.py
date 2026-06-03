from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.tasks.celery_tasks.fast_ping")
def fast_ping() -> str:
    return "fast-ok"


@shared_task(name="apps.tasks.celery_tasks.ai_ping")
def ai_ping() -> str:
    return "ai-ok"


@shared_task(name="apps.tasks.celery_tasks.heavy_ping", soft_time_limit=1500, time_limit=1800)
def heavy_ping() -> str:
    return "heavy-ok"
