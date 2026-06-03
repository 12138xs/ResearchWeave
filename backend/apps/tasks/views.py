from __future__ import annotations

from django.db.models import Count
from django.utils import timezone
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tasks.models import TaskRecord
from apps.tasks.serializers import TaskRecordSerializer


ACTIVE_STATUSES = {TaskRecord.Status.PENDING, TaskRecord.Status.RUNNING}


class TaskListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        queryset = TaskRecord.objects.all()
        status_value = request.query_params.get("status", "").strip()
        task_type = request.query_params.get("task_type", "").strip()
        limit = _positive_int(request.query_params.get("limit"), default=30, maximum=100)

        if status_value:
            queryset = queryset.filter(status=status_value)
        if task_type:
            queryset = queryset.filter(task_type=task_type)

        by_status = dict(queryset.values_list("status").annotate(total=Count("id")).order_by("status"))
        active = sum(by_status.get(status, 0) for status in ACTIVE_STATUSES)
        tasks = queryset.order_by("-updated_at", "-id")[:limit]
        return Response(
            {
                "summary": {
                    "total": sum(by_status.values()),
                    "active": active,
                    "has_active": active > 0,
                    "by_status": by_status,
                },
                "results": TaskRecordSerializer(tasks, many=True).data,
            }
        )


class TaskDetailView(RetrieveAPIView):
    serializer_class = TaskRecordSerializer
    permission_classes = [AllowAny]
    queryset = TaskRecord.objects.all()


class TaskStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        requested_ids = _parse_ids(request.query_params.get("ids", ""))
        tasks = list(TaskRecord.objects.filter(id__in=requested_ids))
        by_id = {task.id: task for task in tasks}
        ordered_tasks = [by_id[task_id] for task_id in requested_ids if task_id in by_id]
        return Response(
            {
                "tasks": TaskRecordSerializer(ordered_tasks, many=True).data,
                "next_poll_after_ms": _next_poll_after_ms(ordered_tasks),
            }
        )


def _parse_ids(value: str) -> list[int]:
    ids = []
    for item in value.split(","):
        item = item.strip()
        if not item.isdigit():
            continue
        parsed = int(item)
        if parsed > 0 and parsed not in ids:
            ids.append(parsed)
    return ids[:50]


def _next_poll_after_ms(tasks: list[TaskRecord]) -> int:
    active_delays = []
    now = timezone.now()
    for task in tasks:
        if task.status == TaskRecord.Status.PENDING:
            active_delays.append(1000)
        elif task.status == TaskRecord.Status.RUNNING:
            age_seconds = max(0.0, (now - task.updated_at).total_seconds())
            if age_seconds < 30:
                active_delays.append(2000)
            elif age_seconds < 180:
                active_delays.append(5000)
            else:
                active_delays.append(12000)
    return min(active_delays) if active_delays else 0


def _positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)
