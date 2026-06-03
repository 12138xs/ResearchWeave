from __future__ import annotations

from django.urls import path

from apps.experiments.views import (
    ExperimentDetailView,
    ExperimentListView,
    ExperimentRunDetailView,
    ExperimentRunExecuteView,
    ExperimentRunListView,
)

urlpatterns = [
    path("experiments/", ExperimentListView.as_view(), name="experiment-list"),
    path("experiments/<int:pk>/", ExperimentDetailView.as_view(), name="experiment-detail"),
    path("experiments/<int:pk>/runs/", ExperimentRunListView.as_view(), name="experiment-run-list"),
    path("experiments/runs/<int:run_id>/", ExperimentRunDetailView.as_view(), name="experiment-run-detail"),
    path("experiments/runs/<int:run_id>/execute/", ExperimentRunExecuteView.as_view(), name="experiment-run-execute"),
]
