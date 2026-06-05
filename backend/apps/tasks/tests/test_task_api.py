from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.tasks.models import TaskRecord


class TaskApiTests(TestCase):
    def test_lists_recent_tasks_with_summary(self) -> None:
        TaskRecord.objects.create(
            task_type="paper_light_process",
            status=TaskRecord.Status.SUCCESS,
            progress=100,
            stage="light_ready",
            object_type="paper",
            object_id=11,
        )
        running = TaskRecord.objects.create(
            task_type="paper_ai_light_process",
            status=TaskRecord.Status.RUNNING,
            progress=45,
            stage="ai_light_profile",
            object_type="paper",
            object_id=12,
        )

        response = self.client.get("/api/tasks/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["active"], 1)
        self.assertTrue(payload["summary"]["has_active"])
        self.assertEqual(payload["summary"]["by_status"]["running"], 1)
        self.assertEqual(payload["results"][0]["id"], running.id)
        self.assertEqual(payload["results"][0]["label"], "AI 轻读概览")

    def test_filters_tasks_by_status(self) -> None:
        TaskRecord.objects.create(task_type="fast_ping", status=TaskRecord.Status.SUCCESS, progress=100)
        TaskRecord.objects.create(task_type="heavy_ping", status=TaskRecord.Status.RUNNING, progress=10)

        response = self.client.get("/api/tasks/?status=running")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["task_type"], "heavy_ping")

    def test_retrieves_task_detail(self) -> None:
        task = TaskRecord.objects.create(
            task_type="paper_light_process",
            status=TaskRecord.Status.FAILED,
            progress=100,
            stage="failed",
            error="PDF text extraction failed",
        )

        response = self.client.get(f"/api/tasks/{task.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], task.id)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "PDF text extraction failed")

    def test_status_endpoint_returns_requested_tasks_and_adaptive_poll_delay(self) -> None:
        pending = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            progress=0,
            stage="queued",
        )
        running = TaskRecord.objects.create(
            task_type="paper_ai_light_process",
            status=TaskRecord.Status.RUNNING,
            progress=50,
            stage="ai_light_profile",
        )
        TaskRecord.objects.filter(pk=running.pk).update(updated_at=timezone.now() - timedelta(seconds=45))
        finished = TaskRecord.objects.create(
            task_type="fast_ping",
            status=TaskRecord.Status.SUCCESS,
            progress=100,
            stage="ok",
        )

        response = self.client.get(f"/api/tasks/status/?ids={pending.id},{running.id},{finished.id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["tasks"]], [pending.id, running.id, finished.id])
        self.assertEqual(payload["next_poll_after_ms"], 1000)

    def test_status_endpoint_stops_polling_when_requested_tasks_are_terminal(self) -> None:
        finished = TaskRecord.objects.create(
            task_type="fast_ping",
            status=TaskRecord.Status.SUCCESS,
            progress=100,
            stage="ok",
        )

        response = self.client.get(f"/api/tasks/status/?ids={finished.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["next_poll_after_ms"], 0)
