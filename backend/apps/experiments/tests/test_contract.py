from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import reverse

from apps.experiments.models import ExperimentProject, ExperimentRun


class ExperimentContractTests(SimpleTestCase):
    def test_project_and_run_models_expose_minimal_reproduction_fields(self) -> None:
        project_fields = {field.name for field in ExperimentProject._meta.fields}
        run_fields = {field.name for field in ExperimentRun._meta.fields}

        for field_name in {
            "title",
            "slug",
            "paper",
            "document",
            "space",
            "status",
            "owner",
            "objective",
            "protocol_markdown",
            "repo_url",
            "environment_json",
        }:
            self.assertIn(field_name, project_fields)

        for field_name in {
            "project",
            "status",
            "params_json",
            "metrics_json",
            "artifact_keys",
            "notes",
            "started_at",
            "finished_at",
            "created_by",
        }:
            self.assertIn(field_name, run_fields)

        self.assertEqual(ExperimentProject.Status.PLANNED, "planned")
        self.assertEqual(ExperimentRun.Status.SUCCESS, "success")

    def test_experiment_urls_follow_resource_shape(self) -> None:
        self.assertEqual(reverse("experiment-list"), "/api/experiments/")
        self.assertEqual(reverse("experiment-detail", kwargs={"pk": 1}), "/api/experiments/1/")
        self.assertEqual(reverse("experiment-run-list", kwargs={"pk": 1}), "/api/experiments/1/runs/")
        self.assertEqual(reverse("experiment-run-detail", kwargs={"run_id": 2}), "/api/experiments/runs/2/")
        self.assertEqual(reverse("experiment-run-execute", kwargs={"run_id": 2}), "/api/experiments/runs/2/execute/")
