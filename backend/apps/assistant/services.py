from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.assistant.models import AssistantExchange, AssistantSession
from apps.tasks.models import TaskRecord


def sync_task(exchange):
    if exchange.task_id:
        TaskRecord.objects.filter(pk=exchange.task_id).update(
            status={"queued": "pending", "running": "running", "completed": "success", "failed": "failed", "cancelled": "failed"}[exchange.status],
            stage=exchange.progress[:80], progress=100 if exchange.status == "completed" else 0,
            result={"exchange_status": exchange.status, "attempt": exchange.attempt, **exchange.usage},
            error=exchange.error, updated_at=timezone.now())


def update_execution(exchange_id, attempt, expected, **values):
    with transaction.atomic():
        row = AssistantExchange.objects.select_for_update().filter(pk=exchange_id, attempt=attempt, status=expected).first()
        if not row:
            return False
        for key, value in values.items():
            setattr(row, key, value)
        row.save(update_fields=[*values, "updated_at"])
        sync_task(row)
        return True


def new_task(exchange):
    exchange.task = TaskRecord.objects.create(task_type="research_agent", created_by=exchange.session.created_by,
        object_type="assistant_exchange", object_id=exchange.pk, stage="等待后台研究助理")
    exchange.save(update_fields=["task"])


class Conflict(APIException):
    status_code = 409
    default_detail = "当前会话已有进行中的问题，请等待或取消。"


def _publish(exchange):
    from apps.assistant.tasks import answer_question
    try:
        answer_question.apply_async(args=[exchange.pk, exchange.attempt], queue="ai_q", retry=False)
    except Exception:
        update_execution(exchange.pk, exchange.attempt, "queued", status="failed", error="暂时无法提交后台任务，请重试。")


def create_assistant_exchange(session, question, request_id):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=session.created_by_id)
        AssistantSession.objects.select_for_update().get(pk=session.pk)
        existing = session.exchanges.filter(request_id=request_id).first()
        if existing:
            if existing.question != question:
                raise Conflict("同一请求编号不能用于不同问题。")
            return existing
        if session.exchanges.filter(status__in=["queued", "running"]).exists():
            raise Conflict()
        if AssistantExchange.objects.filter(session__created_by_id=session.created_by_id, status__in=["queued", "running"]).count() >= 2:
            raise Conflict("每人最多同时执行两个研究问题，请等待或取消已有任务。")
        exchange = AssistantExchange.objects.create(session=session, question=question, request_id=request_id,
            status="queued", progress="等待后台研究助理")
        new_task(exchange)
        session.save(update_fields=["updated_at"])
        transaction.on_commit(lambda: _publish(exchange))
    exchange.refresh_from_db()
    return exchange


def control_exchange(exchange, action, attempt):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=exchange.session.created_by_id)
        AssistantSession.objects.select_for_update().get(pk=exchange.session_id)
        exchange = AssistantExchange.objects.select_for_update().get(pk=exchange.pk)
        if exchange.attempt != attempt:
            return exchange
        if action == "cancel":
            if exchange.status in ["queued", "running"]:
                exchange.status, exchange.progress = "cancelled", "已取消；在途模型请求结束后丢弃结果"
                exchange.save(update_fields=["status", "progress", "updated_at"])
                sync_task(exchange)
        elif action == "retry":
            stale = exchange.updated_at < timezone.now() - timedelta(minutes=5)
            if exchange.status not in ["failed", "cancelled"] and not (stale and exchange.status in ["queued", "running"]):
                raise Conflict("任务尚在执行或已经完成。超过五分钟无进度时可重试。")
            if exchange.session.exchanges.exclude(pk=exchange.pk).filter(status__in=["queued", "running"]).exists():
                raise Conflict()
            if AssistantExchange.objects.filter(session__created_by_id=exchange.session.created_by_id,
                    status__in=["queued", "running"]).exclude(pk=exchange.pk).count() >= 2:
                raise Conflict("每人最多同时执行两个研究问题。")
            if exchange.task_id:
                TaskRecord.objects.filter(pk=exchange.task_id).update(status="failed", stage="已被新尝试替代", updated_at=timezone.now())
            exchange.attempt += 1
            exchange.status, exchange.error, exchange.progress = "queued", "", "等待重试"
            exchange.answer, exchange.sources, exchange.usage = "", [], {}
            exchange.save()
            new_task(exchange)
            transaction.on_commit(lambda: _publish(exchange))
    exchange.refresh_from_db()
    return exchange
