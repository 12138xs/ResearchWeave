from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.db import IntegrityError, transaction

from apps.papers.models import Paper, PaperDeepProfile, PaperLightProfile
from apps.papers.tasks import run_paper_deep_process_task
from apps.tasks.models import TaskRecord


class PaperDeepProcessingTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="member", password="member-password")
        self.client.login(username=self.user.username, password="member-password")

    def _fake_pdf_reader(self, text: str):
        class FakePage:
            def extract_text(self) -> str:
                return text

        class FakeReader:
            def __init__(self, path: str) -> None:
                self.path = path
                self.pages = [FakePage()]

        return FakeReader

    @patch("apps.papers.tasks.run_paper_deep_process_task.apply_async")
    def test_trigger_deep_process_creates_heavy_task(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(
            title="PINNsFormer",
            status=Paper.Status.LIGHT_READY,
            source_pdf_path="quarantine/uploads/pinnsformer.pdf",
        )

        response = self.client.post(f"/api/papers/{paper.id}/trigger-deep-process/")

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["paper"]["status"], "deep_processing")
        self.assertIsNone(payload["paper"]["deep_profile"])
        self.assertEqual(payload["task"]["task_type"], "deep_process_paper")
        self.assertEqual(payload["task"]["status"], "pending")
        self.assertEqual(payload["task"]["stage"], "queued")
        self.assertEqual(payload["task"]["progress"], 0)
        mocked_apply_async.assert_called_once()
        self.assertEqual(mocked_apply_async.call_args.kwargs["queue"], "heavy_q")

    @patch("apps.papers.tasks.run_paper_deep_process_task.apply_async")
    def test_trigger_deep_process_stores_optional_guidance(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(
            title="PINNsFormer",
            status=Paper.Status.LIGHT_READY,
            source_pdf_path="quarantine/uploads/pinnsformer.pdf",
        )

        response = self.client.post(
            f"/api/papers/{paper.id}/trigger-deep-process/",
            {"guidance": "重点关注方法公式和复现实验"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        task = TaskRecord.objects.get(object_type="paper", object_id=paper.id, task_type="deep_process_paper")
        self.assertEqual(task.result["guidance"], "重点关注方法公式和复现实验")
        mocked_apply_async.assert_called_once()

    @patch("apps.papers.tasks.run_paper_deep_process_task.apply_async")
    def test_logged_in_deep_process_accepts_csrf_token(self, mocked_apply_async) -> None:
        client = Client(enforce_csrf_checks=True)
        client.login(username=self.user.username, password="member-password")
        client.get("/api/me/")
        csrf_token = client.cookies["csrftoken"].value
        paper = Paper.objects.create(
            title="PINNsFormer",
            status=Paper.Status.LIGHT_READY,
            source_pdf_path="quarantine/uploads/pinnsformer.pdf",
        )

        response = client.post(
            f"/api/papers/{paper.id}/trigger-deep-process/",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 202)
        mocked_apply_async.assert_called_once()

    @patch("apps.papers.tasks.run_paper_deep_process_task.apply_async")
    def test_anonymous_deep_process_is_rejected(self, mocked_apply_async) -> None:
        self.client.logout()
        paper = Paper.objects.create(
            title="PINNsFormer",
            status=Paper.Status.LIGHT_READY,
            source_pdf_path="quarantine/uploads/pinnsformer.pdf",
        )

        response = self.client.post(f"/api/papers/{paper.id}/trigger-deep-process/")

        self.assertEqual(response.status_code, 403)
        mocked_apply_async.assert_not_called()

    @patch("apps.papers.tasks.run_paper_deep_process_task.apply_async")
    def test_trigger_deep_process_marks_task_failed_if_publish_fails(self, mocked_apply_async) -> None:
        mocked_apply_async.side_effect = RuntimeError("broker unavailable")
        paper = Paper.objects.create(
            title="PINNsFormer",
            status=Paper.Status.LIGHT_READY,
            source_pdf_path="quarantine/uploads/pinnsformer.pdf",
        )

        response = self.client.post(f"/api/papers/{paper.id}/trigger-deep-process/")

        self.assertEqual(response.status_code, 503)
        paper.refresh_from_db()
        task = TaskRecord.objects.get(object_type="paper", object_id=paper.id, task_type="deep_process_paper")
        self.assertEqual(paper.status, Paper.Status.LIGHT_READY)
        self.assertEqual(task.status, TaskRecord.Status.FAILED)
        self.assertEqual(task.stage, "publish_failed")
        self.assertEqual(task.result["restored_paper_status"], Paper.Status.LIGHT_READY)

    @patch("apps.papers.tasks.run_paper_deep_process_task.apply_async")
    def test_trigger_deep_process_rejects_unprocessable_paper_without_active_task(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(
            title="PINNsFormer",
            status=Paper.Status.UPLOADED,
            source_pdf_path="quarantine/uploads/pinnsformer.pdf",
        )

        response = self.client.post(f"/api/papers/{paper.id}/trigger-deep-process/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(TaskRecord.objects.count(), 0)
        mocked_apply_async.assert_not_called()

    @patch("apps.papers.tasks.run_paper_deep_process_task.apply_async")
    def test_trigger_deep_process_requires_pdf_without_active_task(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)

        response = self.client.post(f"/api/papers/{paper.id}/trigger-deep-process/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(TaskRecord.objects.count(), 0)
        mocked_apply_async.assert_not_called()

    @patch("apps.papers.tasks.run_paper_deep_process_task.apply_async")
    def test_trigger_deep_process_reuses_active_task(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.DEEP_PROCESSING)
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.RUNNING,
            progress=30,
            stage="placeholder_sections",
            object_type="paper",
            object_id=paper.id,
        )

        response = self.client.post(f"/api/papers/{paper.id}/trigger-deep-process/")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["task"]["id"], task.id)
        mocked_apply_async.assert_not_called()

    def test_detail_includes_active_deep_processing_task(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.DEEP_PROCESSING)
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.RUNNING,
            progress=45,
            stage="placeholder_sections",
            object_type="paper",
            object_id=paper.id,
        )

        response = self.client.get(f"/api/papers/{paper.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["active_deep_task"]["id"], task.id)
        self.assertEqual(payload["active_deep_task"]["progress"], 45)

    def test_local_pdf_worker_creates_active_deep_profile_version(self) -> None:
        pdf_text = (
            "Abstract\nThis paper studies physics-informed token transformers.\n"
            "Introduction\nPDE solvers need data-efficient sequence models.\n"
            "Methods\nThe residual u_t + u u_x - nu u_xx = 0 is minimized.\n"
            "Experiments\nFigure 1 compares predicted and reference fields.\n"
            "Results\nRelative L2 error improves on Burgers equation.\n"
            "Conclusion\nThe method is reproducible with standard configs.\nReferences\n"
        )
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/paper.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n% test pdf")
            paper = Paper.objects.create(
                title="Physics-informed token transformer for PDEs",
                status=Paper.Status.LIGHT_READY,
                abstract="A transformer method for PDE operator learning with u_t + u u_x = nu u_xx constraints.",
                source_pdf_path="quarantine/uploads/paper.pdf",
            )
            PaperLightProfile.objects.create(
                paper=paper,
                version=1,
                is_active=True,
                generator="rule_based_v1",
                background="Learning PDE dynamics with physics-informed transformers.",
            )
            old_profile = PaperDeepProfile.objects.create(
                paper=paper,
                version=1,
                is_active=True,
                parser_name="placeholder_deep_v1",
                summary="older result",
            )
            task = TaskRecord.objects.create(
                task_type="deep_process_paper",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)), patch(
                "apps.papers.deep_parser.PdfReader",
                self._fake_pdf_reader(pdf_text),
            ), patch(
                "apps.papers.deep_parser.call_minimax_chat",
                side_effect=RuntimeError("LLM disabled in test"),
            ):
                result = run_paper_deep_process_task.run(paper.id, task.id)

        self.assertEqual(result["paper_id"], paper.id)
        self.assertFalse(result["placeholder"])
        self.assertEqual(result["parser_name"], "local_pdf_deep_v1")
        old_profile.refresh_from_db()
        self.assertFalse(old_profile.is_active)
        paper.refresh_from_db()
        self.assertEqual(paper.status, Paper.Status.DEEP_READY)
        active_profile = paper.deep_profiles.get(is_active=True)
        self.assertEqual(active_profile.version, 2)
        self.assertEqual(
            [section["title"] for section in active_profile.sections],
            ["引言与研究背景", "方法介绍", "核心结果与结论", "总结"],
        )
        for section in active_profile.sections:
            self.assertGreaterEqual(len(section.get("evidence", [])), 1)
            self.assertNotIn("placeholder", section["summary"].lower())
            self.assertRegex(section["summary"], r"[\u4e00-\u9fff]")
            self.assertGreaterEqual(len(section["summary"]), 420)
        self.assertGreaterEqual(len(active_profile.figures), 1)
        self.assertGreaterEqual(len(active_profile.formulas), 1)
        self.assertTrue(any("u_t" in item.get("text", "") for item in active_profile.formulas))
        self.assertNotIn("placeholder", active_profile.summary.lower())
        self.assertNotIn("pypdf", active_profile.summary.lower())
        self.assertNotIn("upload", active_profile.summary.lower())
        self.assertNotIn("storage", active_profile.summary.lower())
        self.assertNotIn("pypdf", active_profile.reproduction_notes.lower())
        self.assertNotIn("storage", active_profile.reproduction_notes.lower())
        self.assertTrue(any("```text" in section["summary"] for section in active_profile.sections))
        self.assertTrue(any("###" in section["summary"] for section in active_profile.sections))
        self.assertIn("configs/", active_profile.reproduction_notes)
        self.assertIn("数据集或基准", active_profile.reproduction_notes)
        self.assertIn("评价指标", active_profile.reproduction_notes)
        self.assertIn("消融", active_profile.reproduction_notes)
        self.assertIn("随机种子", active_profile.reproduction_notes)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskRecord.Status.SUCCESS)
        self.assertEqual(task.stage, "deep_ready")
        self.assertEqual(task.result["deep_profile_id"], active_profile.id)

    def test_deep_worker_uses_next_available_version_number(self) -> None:
        pdf_text = "Introduction\nPhysics-informed token transformer.\nMethods\nu_t + u u_x = 0.\nResults\nFigure 1 shows error.\n"
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/paper.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n% test pdf")
            paper = Paper.objects.create(
                title="Physics-informed token transformer",
                status=Paper.Status.LIGHT_READY,
                source_pdf_path="quarantine/uploads/paper.pdf",
            )
            PaperDeepProfile.objects.create(
                paper=paper,
                version=1,
                is_active=False,
                parser_name="placeholder_deep_v1",
                summary="v1",
            )
            PaperDeepProfile.objects.create(
                paper=paper,
                version=3,
                is_active=True,
                parser_name="placeholder_deep_v1",
                summary="v3",
            )
            task = TaskRecord.objects.create(
                task_type="deep_process_paper",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)), patch(
                "apps.papers.deep_parser.PdfReader",
                self._fake_pdf_reader(pdf_text),
            ), patch(
                "apps.papers.deep_parser.call_minimax_chat",
                side_effect=RuntimeError("LLM disabled in test"),
            ):
                run_paper_deep_process_task.run(paper.id, task.id)

        active_profile = paper.deep_profiles.get(is_active=True)
        self.assertEqual(active_profile.version, 4)

    def test_deep_worker_triggers_annotation_anchor_validation(self) -> None:
        pdf_text = "Introduction\nPhysics-informed token transformer.\nMethods\nu_t + u u_x = 0.\nResults\nFigure 1 shows error.\n"
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/paper.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n% test pdf")
            paper = Paper.objects.create(
                title="Physics-informed token transformer",
                status=Paper.Status.LIGHT_READY,
                source_pdf_path="quarantine/uploads/paper.pdf",
            )
            task = TaskRecord.objects.create(
                task_type="deep_process_paper",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with patch("apps.papers.deep_processing.validate_annotation_anchors") as mocked_validate_anchors:
                mocked_validate_anchors.return_value = {
                    "paper_id": paper.id,
                    "deep_profile_id": None,
                    "reason": "deep_profile_created",
                    "checked_count": 0,
                    "active_count": 0,
                    "fuzzy_matched_count": 0,
                    "orphaned_count": 0,
                    "skipped": True,
                    "validated_at": "2026-05-12T00:00:00+08:00",
                }
                with override_settings(STORAGE_ROOT=Path(tmpdir)), patch(
                    "apps.papers.deep_parser.PdfReader",
                    self._fake_pdf_reader(pdf_text),
                ), patch(
                    "apps.papers.deep_parser.call_minimax_chat",
                    side_effect=RuntimeError("LLM disabled in test"),
                ):
                    run_paper_deep_process_task.run(paper.id, task.id)

        mocked_validate_anchors.assert_called_once()
        call_kwargs = mocked_validate_anchors.call_args.kwargs
        self.assertEqual(call_kwargs["paper"].id, paper.id)
        self.assertEqual(call_kwargs["deep_profile"].paper_id, paper.id)
        task.refresh_from_db()
        self.assertTrue(task.result["annotation_validation"]["skipped"])

    def test_lists_deep_profile_versions_for_paper(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer")
        inactive = PaperDeepProfile.objects.create(
            paper=paper,
            version=1,
            is_active=False,
            parser_name="placeholder_deep_v1",
            summary="v1",
        )
        active = PaperDeepProfile.objects.create(
            paper=paper,
            version=2,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="v2",
        )

        response = self.client.get(f"/api/papers/{paper.id}/deep-profiles/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["active"]["id"], active.id)
        self.assertEqual([item["id"] for item in payload["results"]], [active.id, inactive.id])

    def test_activates_deep_profile_version(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.DEEP_READY)
        old_profile = PaperDeepProfile.objects.create(
            paper=paper,
            version=1,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="v1",
        )
        target_profile = PaperDeepProfile.objects.create(
            paper=paper,
            version=2,
            is_active=False,
            parser_name="placeholder_deep_v1",
            summary="v2",
        )

        response = self.client.post(f"/api/papers/{paper.id}/deep-profiles/{target_profile.id}/activate/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["active"]["id"], target_profile.id)
        self.assertIn("annotation_validation", payload)
        old_profile.refresh_from_db()
        paper.refresh_from_db()
        target_profile.refresh_from_db()
        self.assertFalse(old_profile.is_active)
        self.assertTrue(target_profile.is_active)
        self.assertEqual(paper.status, Paper.Status.DEEP_READY)

    def test_activate_deep_profile_rejects_profile_from_another_paper(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer")
        other_paper = Paper.objects.create(title="Other")
        other_profile = PaperDeepProfile.objects.create(
            paper=other_paper,
            version=1,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="other",
        )

        response = self.client.post(f"/api/papers/{paper.id}/deep-profiles/{other_profile.id}/activate/")

        self.assertEqual(response.status_code, 404)

    def test_deletes_deep_profile_and_renumbers_remaining_versions(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.DEEP_READY)
        first = PaperDeepProfile.objects.create(
            paper=paper,
            version=1,
            is_active=False,
            parser_name="placeholder_deep_v1",
            summary="v1",
        )
        second = PaperDeepProfile.objects.create(
            paper=paper,
            version=2,
            is_active=False,
            parser_name="placeholder_deep_v1",
            summary="v2",
        )
        third = PaperDeepProfile.objects.create(
            paper=paper,
            version=3,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="v3",
        )

        response = self.client.delete(f"/api/papers/{paper.id}/deep-profiles/{second.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["results"]], [third.id, first.id])
        self.assertEqual([item["version"] for item in payload["results"]], [2, 1])
        self.assertEqual(payload["active"]["id"], third.id)
        self.assertFalse(PaperDeepProfile.objects.filter(pk=second.pk).exists())

    def test_deleting_active_deep_profile_promotes_latest_remaining_profile(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.DEEP_READY)
        first = PaperDeepProfile.objects.create(
            paper=paper,
            version=1,
            is_active=False,
            parser_name="placeholder_deep_v1",
            summary="v1",
        )
        active = PaperDeepProfile.objects.create(
            paper=paper,
            version=2,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="v2",
        )

        response = self.client.delete(f"/api/papers/{paper.id}/deep-profiles/{active.id}/")

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        paper.refresh_from_db()
        self.assertTrue(first.is_active)
        self.assertEqual(first.version, 1)
        self.assertEqual(paper.status, Paper.Status.DEEP_READY)
        self.assertEqual(response.json()["active"]["id"], first.id)

    def test_deleting_last_deep_profile_without_light_profile_clears_deep_ready_status(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.DEEP_READY)
        profile = PaperDeepProfile.objects.create(
            paper=paper,
            version=1,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="v1",
        )

        response = self.client.delete(f"/api/papers/{paper.id}/deep-profiles/{profile.id}/")

        self.assertEqual(response.status_code, 200)
        paper.refresh_from_db()
        self.assertIsNone(response.json()["active"])
        self.assertEqual(response.json()["results"], [])
        self.assertEqual(paper.status, Paper.Status.UPLOADED)

    def test_deleting_last_deep_profile_with_light_profile_returns_to_light_ready(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.DEEP_READY)
        PaperLightProfile.objects.create(paper=paper, version=1, is_active=True, background="bg")
        profile = PaperDeepProfile.objects.create(
            paper=paper,
            version=1,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="v1",
        )

        response = self.client.delete(f"/api/papers/{paper.id}/deep-profiles/{profile.id}/")

        self.assertEqual(response.status_code, 200)
        paper.refresh_from_db()
        self.assertEqual(paper.status, Paper.Status.LIGHT_READY)

    def test_one_active_deep_profile_per_paper_is_enforced(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer")
        PaperDeepProfile.objects.create(
            paper=paper,
            version=1,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="v1",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            PaperDeepProfile.objects.create(
                paper=paper,
                version=2,
                is_active=True,
                parser_name="placeholder_deep_v1",
                summary="v2",
            )

    @patch("apps.papers.deep_processing._process_deep_profile")
    def test_failed_deep_processing_preserves_active_deep_profile(self, mocked_process) -> None:
        mocked_process.side_effect = RuntimeError("parser unavailable")
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.DEEP_READY)
        active_profile = PaperDeepProfile.objects.create(
            paper=paper,
            version=1,
            is_active=True,
            parser_name="placeholder_deep_v1",
            summary="stable result",
        )
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        with self.assertRaises(RuntimeError):
            run_paper_deep_process_task.run(paper.id, task.id)

        paper.refresh_from_db()
        task.refresh_from_db()
        active_profile.refresh_from_db()
        self.assertEqual(paper.status, Paper.Status.DEEP_READY)
        self.assertTrue(active_profile.is_active)
        self.assertEqual(task.status, TaskRecord.Status.FAILED)
        self.assertEqual(task.stage, "failed")
        self.assertEqual(task.result["active_deep_profile_id"], active_profile.id)
        self.assertEqual(task.result["restored_paper_status"], Paper.Status.DEEP_READY)

    @patch("apps.papers.deep_processing._process_deep_profile")
    def test_failed_deep_processing_restores_light_ready_when_no_deep_profile(self, mocked_process) -> None:
        mocked_process.side_effect = RuntimeError("parser unavailable")
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)
        light_profile = PaperLightProfile.objects.create(
            paper=paper,
            version=1,
            is_active=True,
            generator="rule_based_v1",
            background="background",
        )
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        with self.assertRaises(RuntimeError):
            run_paper_deep_process_task.run(paper.id, task.id)

        paper.refresh_from_db()
        task.refresh_from_db()
        light_profile.refresh_from_db()
        self.assertEqual(paper.status, Paper.Status.LIGHT_READY)
        self.assertTrue(light_profile.is_active)
        self.assertEqual(task.status, TaskRecord.Status.FAILED)
        self.assertEqual(task.result["active_light_profile_id"], light_profile.id)
        self.assertEqual(task.result["restored_paper_status"], Paper.Status.LIGHT_READY)

    def test_failed_deep_processing_tolerates_non_dict_task_result(self) -> None:
        paper = Paper.objects.create(title="PINNsFormer", status=Paper.Status.LIGHT_READY)
        PaperLightProfile.objects.create(
            paper=paper,
            version=1,
            is_active=True,
            generator="rule_based_v1",
            background="background",
        )
        task = TaskRecord.objects.create(
            task_type="deep_process_paper",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
            result=["legacy"],
        )

        with patch("apps.papers.deep_processing._process_deep_profile") as mocked_process:
            mocked_process.side_effect = RuntimeError("parser unavailable")
            with self.assertRaises(RuntimeError):
                run_paper_deep_process_task.run(paper.id, task.id)

        task.refresh_from_db()
        paper.refresh_from_db()
        self.assertEqual(task.status, TaskRecord.Status.FAILED)
        self.assertEqual(task.result["restored_paper_status"], Paper.Status.LIGHT_READY)
        self.assertEqual(paper.status, Paper.Status.LIGHT_READY)
