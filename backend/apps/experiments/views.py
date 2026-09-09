from __future__ import annotations

from math import ceil

from django.shortcuts import get_object_or_404
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import ReadOnlyOrAuthenticatedWriteMixin
from apps.experiments.models import ExperimentRun
from apps.experiments.selectors import accessible_experiments
from apps.experiments.serializers import ExperimentProjectSerializer, ExperimentRunSerializer
from apps.experiments.services import create_experiment_run, enqueue_experiment_run
from apps.tasks.serializers import TaskRecordSerializer


class ExperimentListView(ReadOnlyOrAuthenticatedWriteMixin, ListCreateAPIView):
    serializer_class = ExperimentProjectSerializer
    default_page_size = 25
    max_page_size = 100

    def get_queryset(self):
        return accessible_experiments(self.request.user, params=self.request.query_params)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user if self.request.user.is_authenticated else None)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        count = queryset.count()
        page = _positive_int(request.query_params.get("page"), default=1)
        page_size = _positive_int(request.query_params.get("page_size"), default=self.default_page_size, maximum=self.max_page_size)
        total_pages = max(1, ceil(count / page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size
        serializer = self.get_serializer(queryset[offset : offset + page_size], many=True)
        return Response({"count": count, "page": page, "page_size": page_size, "total_pages": total_pages, "results": serializer.data})


class ExperimentDetailView(ReadOnlyOrAuthenticatedWriteMixin, RetrieveUpdateAPIView):
    serializer_class = ExperimentProjectSerializer

    def get_queryset(self):
        return accessible_experiments(self.request.user, params=self.request.query_params,
                                      write=self.request.method not in {"GET", "HEAD", "OPTIONS"})


class ExperimentRunListView(ReadOnlyOrAuthenticatedWriteMixin, APIView):
    def get(self, request, pk: int):
        project = get_object_or_404(accessible_experiments(request.user), pk=pk)
        return Response(ExperimentRunSerializer(project.runs.all(), many=True).data)

    def post(self, request, pk: int):
        project = get_object_or_404(accessible_experiments(request.user, write=True), pk=pk)
        serializer = ExperimentRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = create_experiment_run(project, serializer.validated_data, user=request.user)
        return Response(ExperimentRunSerializer(run).data, status=201)


class ExperimentRunDetailView(ReadOnlyOrAuthenticatedWriteMixin, RetrieveUpdateAPIView):
    serializer_class = ExperimentRunSerializer
    lookup_url_kwarg = "run_id"

    def get_queryset(self):
        projects = accessible_experiments(self.request.user,
                                         write=self.request.method not in {"GET", "HEAD", "OPTIONS"})
        return ExperimentRun.objects.select_related("project", "created_by").filter(project__in=projects)


class ExperimentRunExecuteView(ReadOnlyOrAuthenticatedWriteMixin, APIView):
    def post(self, request, run_id: int):
        run = get_object_or_404(ExperimentRun.objects.select_related("project").filter(
            project__in=accessible_experiments(request.user, write=True)), pk=run_id)
        task = enqueue_experiment_run(run, user=request.user)
        run.refresh_from_db()
        return Response({"run": ExperimentRunSerializer(run).data, "task": TaskRecordSerializer(task).data}, status=202)


def _positive_int(value: object, *, default: int, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum) if maximum is not None else parsed
