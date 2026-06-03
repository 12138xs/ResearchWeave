from __future__ import annotations

from django.urls import path

from apps.tasks.views import TaskDetailView, TaskListView, TaskStatusView

urlpatterns = [
    path("tasks/", TaskListView.as_view(), name="task-list"),
    path("tasks/status/", TaskStatusView.as_view(), name="task-status"),
    path("tasks/<int:pk>/", TaskDetailView.as_view(), name="task-detail"),
]
