from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from pypdf import PdfWriter

from apps.ai.minimax import MiniMaxResponse
from apps.ai.minimax import MiniMaxAPIError
from apps.papers.models import Paper, PaperLightProfile
from apps.papers.light_processing import (
    _clean_ai_field,
    _extract_authors_from_text,
    _generate_ai_light_profile,
    _looks_like_filename_title,
    _should_backfill_title_from_pdf,
    enqueue_light_processing,
)
from apps.papers.metadata import extract_pdf_metadata
from apps.papers.metadata import title_from_first_page_text
from apps.papers.tasks import run_paper_light_process_task
from apps.papers.tasks import run_paper_upload_postprocess_task
from apps.papers.services.upload import title_from_filename
from apps.library.models import Keyword
from apps.tasks.models import TaskRecord


def sample_pdf_bytes() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()


def sample_pdf_bytes_with_metadata(metadata: dict[str, str]) -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata(metadata)
    writer.write(buffer)
    return buffer.getvalue()


class PaperUploadTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="member", password="member-password")
        self.client.login(username=self.user.username, password="member-password")
        self.upload_postprocess_patcher = patch("apps.papers.tasks.run_paper_upload_postprocess_task.apply_async")
        self.mock_upload_postprocess_apply_async = self.upload_postprocess_patcher.start()
        self.addCleanup(self.upload_postprocess_patcher.stop)

    def test_rejects_anonymous_upload(self) -> None:
        pdf = SimpleUploadedFile("paper.pdf", sample_pdf_bytes(), content_type="application/pdf")

        self.client.logout()
        response = self.client.post("/api/papers/upload/", {"file": pdf, "title": "Blocked"})

        self.assertEqual(response.status_code, 403)

    def test_extracts_authors_from_first_page_text_when_pdf_metadata_is_sparse(self) -> None:
        text = (
            "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks "
            "Zhiyuan Zhao Georgia Institute of Technology Atlanta, GA "
            "Xueying Ding Carnegie Mellon University Pittsburgh, PA "
            "B. Aditya Prakash Georgia Institute of Technology Atlanta, GA "
            "ABSTRACT Physics-Informed Neural Networks have emerged..."
        )

        authors = _extract_authors_from_text(
            text,
            "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks",
        )

        self.assertIn("Zhiyuan Zhao", authors)
        self.assertIn("Xueying Ding", authors)
        self.assertIn("B. Aditya Prakash", authors)

    def test_first_page_title_extraction_ignores_conference_header_and_author_block(self) -> None:
        text = (
            "Published as a conference paper at ICLR 2024 "
            "PINNSFORMER: A TRANSFORMER-BASED FRAMEWORK FOR PHYSICS-INFORMED NEURAL NETWORKS "
            "Zhiyuan Zhao Georgia Institute of Technology Atlanta, GA 30332 leozhao1997@gatech.edu "
            "ABSTRACT Physics-Informed Neural Networks have emerged as a promising tool."
        )

        title = title_from_first_page_text(text)

        self.assertEqual(title, "PINNSFORMER: A TRANSFORMER-BASED FRAMEWORK FOR PHYSICS-INFORMED NEURAL NETWORKS")

    def test_uploads_pdf_to_quarantine_and_creates_paper(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf = SimpleUploadedFile(
                "PINNsFormer.pdf",
                sample_pdf_bytes(),
                content_type="application/pdf",
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.post(
                    "/api/papers/upload/",
                    {"file": pdf, "title": "PINNsFormer", "year": "2024"},
                )

                self.assertEqual(response.status_code, 201)
                payload = response.json()
                self.assertEqual(payload["title"], "PINNsFormer")
                self.assertEqual(payload["year"], 2024)
                self.assertEqual(payload["status"], "uploaded")
                self.assertTrue(payload["source_pdf_path"].startswith("quarantine/uploads/"))
                self.assertEqual(Paper.objects.count(), 1)
                self.assertTrue((Path(tmpdir) / payload["source_pdf_path"]).exists())

    def test_upload_generates_normalized_title_from_pdf_metadata_before_filename(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf = SimpleUploadedFile(
                "arxiv_2301.12345_download_paper_final.pdf",
                sample_pdf_bytes_with_metadata(
                    {
                        "/Title": "  Learning PDE Solution Operators with physics-informed Transformers  ",
                    }
                ),
                content_type="application/pdf",
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.post("/api/papers/upload/", {"file": pdf})

            self.assertEqual(response.status_code, 201)
            self.assertEqual(
                response.json()["title"],
                "Learning PDE Solution Operators with physics-informed Transformers",
            )

    def test_upload_without_extracted_title_queues_metadata_completion_and_ai_overview(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf = SimpleUploadedFile(
                "arXiv_2301.12345_download_final.pdf",
                sample_pdf_bytes(),
                content_type="application/pdf",
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.post("/api/papers/upload/", {"file": pdf})

            self.assertEqual(response.status_code, 201)
            payload = response.json()
            self.assertEqual(payload["title"], "Paper upload")
            self.assertEqual(payload["arxiv_id"], "2301.12345")
            self.assertEqual(payload["source_url"], "https://arxiv.org/abs/2301.12345")
            self.assertEqual(payload["post_upload_task"]["task_type"], "paper_upload_postprocess")
            self.assertEqual(payload["post_upload_task"]["status"], "pending")
            self.assertNotIn("2301", payload["title"])
            self.assertNotIn("download", payload["title"].lower())
            self.mock_upload_postprocess_apply_async.assert_called_once()
            self.assertEqual(self.mock_upload_postprocess_apply_async.call_args.kwargs["queue"], "ai_q")

    def test_upload_extracts_metadata_fields_from_pdf_and_filename(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf = SimpleUploadedFile(
                "arXiv_2402.12345v2_main.pdf",
                sample_pdf_bytes_with_metadata(
                    {
                        "/Title": "Physics Informed Neural Operators for Darcy Flow",
                        "/Author": "Alice Zhang; Bo Li and Carol Wang",
                        "/Subject": "We present a neural operator method for Darcy flow benchmarks.",
                        "/CreationDate": "D:20240203040506Z",
                        "/doi": "10.1234/example.darcy.2024",
                    }
                ),
                content_type="application/pdf",
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.post("/api/papers/upload/", {"file": pdf})

            self.assertEqual(response.status_code, 201)
            payload = response.json()
            self.assertEqual(payload["authors"], ["Alice Zhang", "Bo Li", "Carol Wang"])
            self.assertEqual(payload["year"], 2024)
            self.assertEqual(payload["doi"], "10.1234/example.darcy.2024")
            self.assertEqual(payload["arxiv_id"], "2402.12345")
            self.assertEqual(payload["source_url"], "https://arxiv.org/abs/2402.12345")
            self.assertIn("neural operator method", payload["abstract"])

    def test_paper_list_does_not_expose_quarantine_path(self) -> None:
        Paper.objects.create(title="Hidden path", source_pdf_path="quarantine/uploads/hidden.pdf")

        response = self.client.get("/api/papers/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("source_pdf_path", response.json()[0])

    def test_rejects_non_pdf_upload(self) -> None:
        txt = SimpleUploadedFile("notes.txt", b"not a pdf", content_type="text/plain")

        response = self.client.post("/api/papers/upload/", {"file": txt, "title": "Bad file"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())

    def test_rejects_fake_pdf_upload(self) -> None:
        fake_pdf = SimpleUploadedFile("fake.pdf", b"%PDF-not really a pdf", content_type="application/pdf")

        response = self.client.post("/api/papers/upload/", {"file": fake_pdf, "title": "Fake PDF"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())

    def test_rejects_upload_from_disallowed_network(self) -> None:
        pdf = SimpleUploadedFile("paper.pdf", sample_pdf_bytes(), content_type="application/pdf")

        response = self.client.post(
            "/api/papers/upload/",
            {"file": pdf, "title": "Blocked"},
            REMOTE_ADDR="203.0.113.8",
        )

        self.assertEqual(response.status_code, 403)

    def test_rejects_spoofed_forwarded_for_upload(self) -> None:
        pdf = SimpleUploadedFile("paper.pdf", sample_pdf_bytes(), content_type="application/pdf")

        response = self.client.post(
            "/api/papers/upload/",
            {"file": pdf, "title": "Spoofed"},
            REMOTE_ADDR="203.0.113.8",
            HTTP_X_FORWARDED_FOR="10.89.0.10",
        )

        self.assertEqual(response.status_code, 403)

    def test_rejects_spoofed_real_ip_upload_from_untrusted_remote(self) -> None:
        pdf = SimpleUploadedFile("paper.pdf", sample_pdf_bytes(), content_type="application/pdf")

        response = self.client.post(
            "/api/papers/upload/",
            {"file": pdf, "title": "Spoofed"},
            REMOTE_ADDR="203.0.113.8",
            HTTP_X_REAL_IP="10.89.0.10",
        )

        self.assertEqual(response.status_code, 403)

    def test_allows_upload_from_nginx_real_ip(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf = SimpleUploadedFile("paper.pdf", sample_pdf_bytes(), content_type="application/pdf")

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.post(
                    "/api/papers/upload/",
                    {"file": pdf, "title": "Allowed"},
                    REMOTE_ADDR="10.89.0.2",
                    HTTP_X_REAL_IP="10.89.0.10",
                    HTTP_X_FORWARDED_FOR="203.0.113.8",
                )

            self.assertEqual(response.status_code, 201)

    def test_allows_upload_from_trusted_proxy_forwarded_for_client(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf = SimpleUploadedFile("paper.pdf", sample_pdf_bytes(), content_type="application/pdf")

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.post(
                    "/api/papers/upload/",
                    {"file": pdf, "title": "Allowed through 30888"},
                    REMOTE_ADDR="10.89.0.2",
                    HTTP_X_FORWARDED_FOR="10.89.0.10, 10.89.0.2",
                )

            self.assertEqual(response.status_code, 201)

    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_light_process_enqueues_async_task(self, mocked_apply_async) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="PINN Transformer", source_pdf_path="quarantine/uploads/sample.pdf")

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.post(f"/api/papers/{paper.id}/light-process/")

            self.assertEqual(response.status_code, 202)
            payload = response.json()
            self.assertEqual(payload["paper"]["status"], "light_processing")
            self.assertEqual(payload["task"]["status"], "pending")
            self.assertEqual(payload["task"]["stage"], "queued")
            self.assertEqual(payload["task"]["progress"], 0)
            mocked_apply_async.assert_called_once()
            self.assertEqual(mocked_apply_async.call_args.kwargs["queue"], "fast_q")

    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_ai_light_process_is_routed_to_ai_queue(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(title="PINNsFormer", source_pdf_path="quarantine/uploads/sample.pdf")

        response = self.client.post(
            f"/api/papers/{paper.id}/light-process/",
            {"use_ai": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["task"]["task_type"], "paper_ai_light_process")
        mocked_apply_async.assert_called_once()
        self.assertEqual(mocked_apply_async.call_args.kwargs["queue"], "ai_q")

    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_light_process_reuses_active_task(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(
            title="PINNsFormer",
            source_pdf_path="quarantine/uploads/sample.pdf",
            status=Paper.Status.LIGHT_PROCESSING,
        )
        task = TaskRecord.objects.create(
            task_type="paper_light_process",
            status=TaskRecord.Status.RUNNING,
            progress=40,
            stage="reading_pdf",
            object_type="paper",
            object_id=paper.id,
        )

        response = self.client.post(f"/api/papers/{paper.id}/light-process/")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["task"]["id"], task.id)
        mocked_apply_async.assert_not_called()

    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_ai_light_process_reuses_pending_rule_light_task_for_same_paper(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(
            title="PINNsFormer",
            source_pdf_path="quarantine/uploads/sample.pdf",
            status=Paper.Status.LIGHT_PROCESSING,
        )
        task = TaskRecord.objects.create(
            task_type="paper_light_process",
            status=TaskRecord.Status.PENDING,
            progress=0,
            stage="queued",
            object_type="paper",
            object_id=paper.id,
        )

        returned = enqueue_light_processing(paper, use_ai=True)

        self.assertEqual(returned.id, task.id)
        self.assertEqual(TaskRecord.objects.filter(object_type="paper", object_id=paper.id).count(), 1)
        mocked_apply_async.assert_not_called()

    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_rule_light_process_reuses_pending_ai_light_task_for_same_paper(self, mocked_apply_async) -> None:
        paper = Paper.objects.create(
            title="PINNsFormer",
            source_pdf_path="quarantine/uploads/sample.pdf",
            status=Paper.Status.LIGHT_PROCESSING,
        )
        task = TaskRecord.objects.create(
            task_type="paper_ai_light_process",
            status=TaskRecord.Status.PENDING,
            progress=0,
            stage="queued",
            object_type="paper",
            object_id=paper.id,
        )

        returned = enqueue_light_processing(paper, use_ai=False)

        self.assertEqual(returned.id, task.id)
        self.assertEqual(TaskRecord.objects.filter(object_type="paper", object_id=paper.id).count(), 1)
        mocked_apply_async.assert_not_called()

    @patch("apps.papers.light_processing.Paper.objects.select_for_update")
    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_light_process_enqueue_locks_paper_before_creating_task(self, mocked_apply_async, mocked_lock) -> None:
        paper = Paper.objects.create(title="PINNsFormer", source_pdf_path="quarantine/uploads/sample.pdf")
        mocked_lock.return_value.get.return_value = paper

        with transaction.atomic():
            task = enqueue_light_processing(paper)

        mocked_lock.assert_called_once()
        self.assertEqual(task.status, "pending")
        self.assertEqual(TaskRecord.objects.filter(object_type="paper", object_id=paper.id).count(), 1)
        mocked_apply_async.assert_called_once()

    def test_light_process_worker_extracts_profile_and_keywords(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="PINN Transformer", source_pdf_path="quarantine/uploads/sample.pdf")
            task = TaskRecord.objects.create(
                task_type="paper_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                result = run_paper_light_process_task.run(paper.id, task.id, False)

            self.assertEqual(result["paper_id"], paper.id)
            paper.refresh_from_db()

    @patch("apps.papers.post_upload.suggest_paper_metadata")
    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_upload_postprocess_applies_metadata_and_queues_ai_light_profile(self, mocked_light_apply_async, mocked_suggest) -> None:
        mocked_suggest.return_value = {
            "provider": "web_search+llm",
            "model": "MiniMax-M2.7",
            "suggestions": {
                "title": "Recovered Transformer PDE Paper",
                "authors": ["Alice Zhang"],
                "year": 2024,
                "venue": "ICLR",
                "doi": "",
                "arxiv_id": "2301.12345",
                "source_url": "https://arxiv.org/abs/2301.12345",
                "abstract": "This paper studies transformer models for PDE constraints.",
                "keywords": ["PDE", "Transformer"],
                "confidence": 0.91,
            },
            "evidence": [],
        }
        paper = Paper.objects.create(
            title="Paper upload",
            arxiv_id="2301.12345",
            source_pdf_path="quarantine/uploads/sample.pdf",
        )
        task = TaskRecord.objects.create(
            task_type="paper_upload_postprocess",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        result = run_paper_upload_postprocess_task.run(paper.id, task.id)

        paper.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(paper.title, "Recovered Transformer PDE Paper")
        self.assertEqual(paper.abstract, "This paper studies transformer models for PDE constraints.")
        self.assertEqual(paper.authors, ["Alice Zhang"])
        self.assertEqual(paper.year, 2024)
        self.assertEqual(paper.venue, "ICLR")
        self.assertEqual(set(paper.keywords.values_list("name", flat=True)), {"PDE", "Transformer"})
        self.assertEqual(task.status, TaskRecord.Status.SUCCESS)
        self.assertEqual(task.result["metadata_applied"], True)
        self.assertIn("light_task_id", result)
        mocked_light_apply_async.assert_called_once()
        self.assertEqual(mocked_light_apply_async.call_args.kwargs["queue"], "ai_q")

    @patch("apps.papers.post_upload.suggest_paper_metadata")
    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_upload_postprocess_uses_candidate_title_when_suggestion_title_is_missing(self, mocked_light_apply_async, mocked_suggest) -> None:
        mocked_suggest.return_value = {
            "provider": "web_search+llm",
            "model": "MiniMax-M2.7",
            "suggestions": {
                "title": "",
                "authors": [],
                "year": None,
                "venue": "",
                "keywords": ["PDEs", "PDE", "Physics-Informed Neural Networks", "PINN"],
                "confidence": 0.45,
            },
            "candidates": [
                {
                    "title": "Recovered Candidate Title for PDE Solvers",
                    "source_url": "https://arxiv.org/abs/2501.11111",
                    "arxiv_id": "2501.11111",
                    "keywords": ["PDEs", "PINNs"],
                }
            ],
            "evidence": [],
        }
        alias = Keyword.objects.create(name="PDEs")
        paper = Paper.objects.create(title="Paper upload", source_pdf_path="quarantine/uploads/sample.pdf")
        paper.keywords.add(alias)
        task = TaskRecord.objects.create(
            task_type="paper_upload_postprocess",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        run_paper_upload_postprocess_task.run(paper.id, task.id)

        paper.refresh_from_db()
        self.assertEqual(paper.title, "Recovered Candidate Title for PDE Solvers")
        self.assertEqual(set(paper.keywords.values_list("name", flat=True)), {"PDE", "PINN"})
        self.assertEqual(paper.arxiv_id, "2501.11111")
        mocked_light_apply_async.assert_called_once()

    @patch("apps.papers.post_upload.suggest_paper_metadata")
    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_upload_postprocess_rejects_low_confidence_unmatched_metadata(self, mocked_light_apply_async, mocked_suggest) -> None:
        mocked_suggest.return_value = {
            "provider": "web_search+llm",
            "model": "MiniMax-M2.7",
            "suggestions": {
                "title": "Unrelated Surrogate Model Paper",
                "authors": ["New York"],
                "year": 2023,
                "venue": "NeurIPS",
                "source_url": "https://example.com/unrelated",
                "abstract": "This is unrelated evidence.",
                "keywords": ["Transformer"],
                "confidence": 0.0,
            },
            "candidates": [
                {
                    "title": "Unrelated Surrogate Model Paper",
                    "source_url": "https://example.com/unrelated",
                    "arxiv_id": "2310.02994",
                    "confidence": 0.3,
                }
            ],
            "evidence": [],
        }
        paper = Paper.objects.create(
            title="Paper upload",
            arxiv_id="2501.11111",
            source_pdf_path="quarantine/uploads/sample.pdf",
        )
        task = TaskRecord.objects.create(
            task_type="paper_upload_postprocess",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        run_paper_upload_postprocess_task.run(paper.id, task.id)

        paper.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(paper.title, "Paper upload")
        self.assertEqual(paper.authors, [])
        self.assertIsNone(paper.year)
        self.assertEqual(paper.venue, "")
        self.assertEqual(list(paper.keywords.values_list("name", flat=True)), [])
        self.assertEqual(task.result["metadata_applied"], False)
        self.assertIn("metadata_rejected", task.result)
        mocked_light_apply_async.assert_called_once()

    @patch("apps.papers.post_upload.suggest_paper_metadata")
    @patch("apps.papers.tasks.run_paper_light_process_task.apply_async")
    def test_upload_postprocess_rejects_non_abstract_metadata_text(self, mocked_light_apply_async, mocked_suggest) -> None:
        mocked_suggest.return_value = {
            "provider": "web_search+llm",
            "model": "MiniMax-M2.7",
            "suggestions": {
                "title": "Recovered Transformer PDE Paper",
                "arxiv_id": "2301.12345",
                "source_url": "https://arxiv.org/abs/2301.12345",
                "abstract": (
                    "Published as a conference paper at ICLR 2024. Recovered Transformer PDE Paper. "
                    "Alice Zhang, Bob Lee. This page contains title, authors, and citation links."
                ),
                "confidence": 0.92,
            },
            "evidence": [],
        }
        paper = Paper.objects.create(
            title="Paper upload",
            arxiv_id="2301.12345",
            source_pdf_path="quarantine/uploads/sample.pdf",
        )
        task = TaskRecord.objects.create(
            task_type="paper_upload_postprocess",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        run_paper_upload_postprocess_task.run(paper.id, task.id)

        paper.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(paper.title, "Recovered Transformer PDE Paper")
        self.assertEqual(paper.abstract, "")
        self.assertNotIn("abstract", task.result["applied_fields"])
        mocked_light_apply_async.assert_called_once()

    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_ai_light_process_empty_minimax_answer_falls_back_to_rule_profile(self, mocked_chat) -> None:
        mocked_chat.side_effect = MiniMaxAPIError("MiniMax API returned an empty answer.")
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="Fallback Overview", source_pdf_path="quarantine/uploads/sample.pdf")
            task = TaskRecord.objects.create(
                task_type="paper_ai_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                run_paper_light_process_task.run(paper.id, task.id, True)

        paper.refresh_from_db()
        task.refresh_from_db()
        profile = paper.light_profiles.get(is_active=True)
        self.assertEqual(paper.status, Paper.Status.LIGHT_READY)
        self.assertEqual(task.status, TaskRecord.Status.SUCCESS)
        self.assertEqual(profile.generator, "rule_based_v1")
        self.assertIn("ai_error", task.result)
        self.assertIn("MiniMax API returned an empty answer", task.result["ai_error"])
    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_ai_light_process_worker_can_generate_profile(self, mocked_chat) -> None:
        mocked_chat.return_value = MiniMaxResponse(
            content=(
                '{"paper_type":"Algorithm",'
                '"research_problem":"传统 PINN 在长时间 PDE 演化中误差容易累积，训练稳定性不足。",'
                '"objective":"用 Transformer 结构增强物理约束模型的时序表达能力。",'
                '"core_idea":"把时间片段表示为序列 token，并在损失中继续保留 PDE 残差约束。",'
                '"key_findings":["在多个 PDE 任务上降低误差","对长时间预测更稳定"],'
                '"tldr":"Transformer 增强 PINN",'
                '"taxonomy_hint":{"primary_category":"PINN","keywords":["PINN","Transformer"]},'
                '"evidence_level":"medium",'
                '"uncertainties":["需要核对具体基线和消融设置"]}'
            ),
            model="MiniMax-M2.7",
            usage={"total_tokens": 256},
            raw={},
        )
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="PINNsFormer", source_pdf_path="quarantine/uploads/sample.pdf")
            task = TaskRecord.objects.create(
                task_type="paper_ai_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                result = run_paper_light_process_task.run(paper.id, task.id, True)

            self.assertEqual(result["model"], "MiniMax-M2.7")
            task.refresh_from_db()
            self.assertEqual(task.result["model"], "MiniMax-M2.7")
            self.assertTrue(Paper.objects.get(id=paper.id).keywords.filter(name="PINN").exists())

    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_ai_light_process_expands_too_short_profile_fields(self, mocked_chat) -> None:
        mocked_chat.return_value = MiniMaxResponse(
            content='{"keywords":["PDE"],"background":"太短。","method":"","results":"太短。"}',
            model="MiniMax-M2.7",
            usage={"total_tokens": 64},
            raw={},
        )
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="Physics Informed Operators", source_pdf_path="quarantine/uploads/sample.pdf")
            task = TaskRecord.objects.create(
                task_type="paper_ai_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                run_paper_light_process_task.run(paper.id, task.id, True)

            profile = paper.light_profiles.get(is_active=True)
            for field in [profile.background, profile.method, profile.results]:
                self.assertGreaterEqual(len(field), 120)
                self.assertGreaterEqual(field.count(".") + field.count("\u3002"), 2)
                # mojibake 回归哨兵：这些字符串故意保留，用来防止乱码进入 AI 粗读输出。
                self.assertNotIn("鏂", field)
                self.assertNotIn("绮楄", field)

    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_ai_light_process_accepts_structured_skim_schema(self, mocked_chat) -> None:
        mocked_chat.return_value = MiniMaxResponse(
            content=(
                "## 研究背景\n"
                "现有神经算子比较缺少统一基准，不同论文常在数据集、网格、误差指标和训练预算上各自设定，导致结果难以横向比较。作者因此把问题定位为评测协议不统一，而不是单个模型结构不足。\n\n"
                "本文的目标是建立覆盖多类 PDE 的公平评测流程，让研究者能够在统一数据、统一指标和统一预算下判断不同模型的真实差异，并把该论文归入 Neural Operator 与 PDE Benchmark 方向。\n\n"
                "## 方法原理\n"
                "方法原理上，论文把数据集、误差指标和训练预算固定成统一流程，例如使用 $u_t = \\mathcal{N}(u)$ 描述任务约束。这样做的核心直觉是先控制实验变量，再比较模型能力。\n\n"
                "- 固定数据划分和评价指标\n"
                "- 固定训练预算与模型接口\n\n"
                "## 主要结果\n"
                "主要结果是覆盖多类 PDE，并报告不同模型在相同预算下的差异，为后续模型选择和 related work 写作提供基准依据。\n\n"
                "$$\nE=\\|u-\\hat u\\|_2\n$$\n\n"
                "从粗读角度看，需要后续深度处理继续核对具体数据集、误差数值、基线设置和消融结论，避免把 benchmark 的定性结论误读成普适排名。\n\n"
                "## 关键词\n"
                "- PDE\n- Benchmark\n- Neural Operator\n"
            ),
            model="MiniMax-M2.7",
            usage={"total_tokens": 300},
            raw={},
        )
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="Benchmarking Neural Operators", source_pdf_path="quarantine/uploads/sample.pdf")
            task = TaskRecord.objects.create(
                task_type="paper_ai_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                run_paper_light_process_task.run(paper.id, task.id, True)

        profile = paper.light_profiles.get(is_active=True)
        self.assertNotRegex(profile.background.strip().split("\n", 1)[0], r"^研究背景$")
        self.assertNotRegex(profile.method.strip().split("\n", 1)[0], r"^方法原理$")
        self.assertNotRegex(profile.results.strip().split("\n", 1)[0], r"^主要结果$")
        self.assertIn("\n\n", profile.background)
        self.assertIn("\n\n", profile.method)
        self.assertIn("\n\n", profile.results)
        for field in [profile.background, profile.method, profile.results]:
            self.assertGreaterEqual(len(field), 220)
            self.assertGreaterEqual(field.count("。"), 3)
        self.assertIn("评测协议不统一", profile.background)
        self.assertIn("控制实验变量", profile.method)
        self.assertIn("$u_t = \\mathcal{N}(u)$", profile.method)
        self.assertIn("- 固定数据划分和评价指标", profile.method)
        self.assertIn("后续深度处理继续核对", profile.results)
        self.assertIn("$$", profile.results)
        self.assertCountEqual(profile.keywords, ["PDE", "Benchmark", "Neural Operator"])

    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_ai_light_process_does_not_overwrite_existing_title_from_pdf_header(self, mocked_chat) -> None:
        mocked_chat.return_value = MiniMaxResponse(
            content=(
                '{"research_background":["论文研究物理约束 Transformer，用于改进 PINN 在长时间 PDE 预测中的稳定性。这里保留较长背景说明，避免测试因为质量门槛而回退。",'
                '"已有 PINN 方法在复杂动力学和长时预测下容易累积误差，本文需要继续核对其与 ICLR 论文正文的对应关系。"],'
                '"method_principle":["方法原理是把时间片段组织为序列表示，并结合物理残差训练目标。这里使用较长段落模拟模型返回，确保后端只处理概览而不改标题。",'
                '"该方法仍需要回到论文公式和网络结构图中核对注意力机制、损失函数以及边界条件嵌入方式。"],'
                '"main_results":["主要结果需要从实验表格中核对，包括误差指标、数据集和基线设置。这里不编造具体数字，只说明后续核对方向。",'
                '"系统应保存这些概览文本，但不能把 PDF 首页页眉或作者信息当成新的论文标题写回数据库。"],'
                '"keywords":["PINN","Transformer","PDE"]}'
            ),
            model="MiniMax-M2.7",
            usage={"total_tokens": 300},
            raw={},
        )
        noisy_title = (
            "Published as a conference paper at ICLR 2024 PINN SFORMER : A T RANSFORMER -BASED "
            "FRAME - WORK FOR PHYSICS -I NFORMED NEURAL NETWORKS Zhiyuan Zhao Georgia Institute of Technology"
        )
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes_with_metadata({"/Title": noisy_title}))
            paper = Paper.objects.create(title="Paper upload", source_pdf_path="quarantine/uploads/sample.pdf")
            task = TaskRecord.objects.create(
                task_type="paper_ai_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                run_paper_light_process_task.run(paper.id, task.id, True)

        paper.refresh_from_db()
        self.assertEqual(paper.title, "Paper upload")
        self.assertNotIn("Published as a conference paper", paper.title)

    @patch("apps.papers.light_processing.call_minimax_chat")
    @patch("apps.papers.light_processing.extract_pdf_metadata")
    def test_ai_light_process_preserves_real_title_with_hyphen(self, mocked_extract_metadata, mocked_chat) -> None:
        from apps.papers.metadata import ExtractedPaperMetadata

        mocked_chat.return_value = MiniMaxResponse(
            content=(
                "## 研究背景\n"
                "这篇论文关注物理信息神经网络中的长时预测问题，粗读阶段需要保留现有标题并只生成中文结构化概览，不能因为标题含有连字符就把 PDF 抽取页眉写回数据库。\n\n"
                "已有方法在复杂动力学系统中可能出现误差累积和约束失效，当前测试模拟 AI 粗读任务，验证元数据补全不会覆盖人工整理过的题名。\n\n"
                "## 方法原理\n"
                "方法部分强调把 Transformer 结构与物理残差约束结合，粗读结果只应进入 PaperLightProfile 字段，不能触碰已经规范化的论文标题。\n\n"
                "该流程需要继续核对公式、网络结构和训练目标，但标题字段应保持用户或元数据补全后的稳定结果，避免任务运行造成目录抖动。\n\n"
                "## 主要结果\n"
                "结果部分说明论文可能报告长时预测和泛化能力改进，但具体数值仍需回到表格和实验设置中核验，粗读阶段不编造结论。\n\n"
                "本测试重点是验证 AI 粗读只新增结构化概览和关键词，不因 PDF 页眉抽取结果改变已有规范标题。\n\n"
                "## 关键词\n- PINN\n- Transformer\n- PDE\n"
            ),
            model="MiniMax-M2.7",
            usage={"total_tokens": 420},
            raw={},
        )
        mocked_extract_metadata.return_value = ExtractedPaperMetadata(
            title=(
                "Published as a conference paper at ICLR 2024 PINN SFORMER : A T RANSFORMER -BASED "
                "FRAME - WORK FOR PHYSICS -I NFORMED NEURAL NETWORKS Zhiyuan Zhao Georgia Institute of Technology"
            ),
            text="abstract text about PINN Transformer PDE.",
        )
        paper = Paper.objects.create(
            title="PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks",
            source_pdf_path="quarantine/uploads/sample.pdf",
        )
        task = TaskRecord.objects.create(
            task_type="paper_ai_light_process",
            status=TaskRecord.Status.PENDING,
            object_type="paper",
            object_id=paper.id,
        )

        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                run_paper_light_process_task.run(paper.id, task.id, True)

        paper.refresh_from_db()
        self.assertEqual(
            paper.title,
            "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks",
        )

    def test_title_backfill_only_treats_true_placeholders_or_filenames_as_replaceable(self) -> None:
        self.assertTrue(_looks_like_filename_title("Paper upload"))
        self.assertTrue(_looks_like_filename_title("arXiv_2301.12345_download"))
        self.assertFalse(_looks_like_filename_title("PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks"))
        self.assertFalse(_should_backfill_title_from_pdf("Paper upload", "Published as a conference paper at ICLR 2024 Bad Header"))
        self.assertFalse(_should_backfill_title_from_pdf("Paper upload", "PINN SFORMER : A T RANSFORMER -BASED FRAME - WORK"))
        self.assertTrue(_should_backfill_title_from_pdf("Paper upload", "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks"))

    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_ai_light_process_replaces_english_markdown_with_chinese_fallback(self, mocked_chat) -> None:
        english_background = (
            "This paper studies neural operators for partial differential equations and proposes "
            "a benchmark for comparing different architectures under shared data splits. The "
            "background is useful, but it is intentionally returned in English to verify that the "
            "Chinese quality gate does not store provider output directly."
        )
        english_method = (
            "The method fixes the training budget, the model interface, and the evaluation metric "
            "so different solvers can be compared under the same protocol. This paragraph is long "
            "enough to pass a naive length gate, but it should still be rejected."
        )
        english_results = (
            "The main results report qualitative differences across several PDE tasks and ask the "
            "reader to check all numerical claims in the original tables. This output should not be "
            "copied into the persisted profile because it is not Chinese."
        )
        mocked_chat.return_value = MiniMaxResponse(
            content=(
                f"## 研究背景\n{english_background}\n\n"
                f"{english_background}\n\n"
                f"## 方法原理\n{english_method}\n\n"
                f"{english_method}\n\n"
                f"## 主要结果\n{english_results}\n\n"
                f"{english_results}\n\n"
                "## 关键词\n- PDE\n- Benchmark\n"
            ),
            model="MiniMax-M2.7",
            usage={"total_tokens": 380},
            raw={},
        )
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="English Provider Output", source_pdf_path="quarantine/uploads/sample.pdf")
            task = TaskRecord.objects.create(
                task_type="paper_ai_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                run_paper_light_process_task.run(paper.id, task.id, True)

        profile = paper.light_profiles.get(is_active=True)
        combined = "\n".join([profile.background, profile.method, profile.results])
        self.assertNotIn("This paper studies neural operators", combined)
        self.assertNotIn("The method fixes the training budget", combined)
        self.assertNotIn("The main results report qualitative differences", combined)
        for field in [profile.background, profile.method, profile.results]:
            self.assertGreaterEqual(field.count("\n\n"), 1)
            self.assertGreaterEqual(sum("\u4e00" <= char <= "\u9fff" for char in field), 80)

    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_ai_light_prompt_requests_strict_skim_markdown_contract(self, mocked_chat) -> None:
        mocked_chat.return_value = MiniMaxResponse(
            content=(
                "## 研究背景\n待核对。当前 PDF 文本不足，需要保守概览并记录后续核对方向。\n\n"
                "## 方法原理\n待核对。当前 PDF 文本不足，需要后续查看公式、算法流程和实现说明。\n\n"
                "## 主要结果\n待核对。当前 PDF 文本不足，不能编造实验数字或理论结论。\n\n"
                "## 关键词\n- PDE\n"
            ),
            model="MiniMax-M2.7",
            usage={},
            raw={},
        )
        paper = Paper(title="Prompt Contract")

        _generate_ai_light_profile(paper, "abstract text", ["PDE"])

        messages = mocked_chat.call_args.args[0]
        prompt_text = "\n".join(message["content"] for message in messages)
        self.assertIn("研究背景", prompt_text)
        self.assertIn("方法原理", prompt_text)
        self.assertIn("主要结果", prompt_text)
        self.assertIn("关键词", prompt_text)
        self.assertIn("每部分至少 2 段", prompt_text)
        self.assertIn("每段至少 80 个中文字符", prompt_text)
        self.assertIn("Markdown", prompt_text)
        self.assertIn("只包含以下二级标题", prompt_text)
        self.assertIn("不要返回 JSON", prompt_text)

    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_ai_light_markdown_fields_do_not_store_duplicate_section_headings(self, mocked_chat) -> None:
        mocked_chat.return_value = MiniMaxResponse(
            content=(
                "## 研究背景\n"
                "### 研究背景\n"
                "研究背景部分说明该论文关注 PDE 科学机器学习中的长期预测问题，现有模型在误差累积、约束保持和跨场景泛化上仍有明显不确定性，因此需要先把问题放在可核对的粗读框架中理解。\n\n"
                "本文目标是建立一个保守的知识库入口，让研究者能看到论文可能对应的任务类型、方法类别和后续精读优先级，同时避免把自动摘要误写成已经验证的事实结论。\n\n"
                "## 方法原理\n"
                "### 方法原理\n"
                "方法原理部分强调先从抽取文本中识别模型结构、训练目标、物理残差和评价协议，再判断它是否真的提出新算法，还是主要整理实验流程或应用场景。\n\n"
                "如果论文包含公式、图表或伪代码，粗读阶段只记录其存在和可能作用，不直接补造推导细节；这些内容需要在深度处理中回到原文逐项核对。\n\n"
                "## 主要结果\n"
                "### 主要结果\n"
                "主要结果部分应区分作者声称的发现、当前抽取文本能支持的证据，以及还必须人工核对的误差指标、基线设置、消融实验和泛化条件。\n\n"
                "当证据不足时，系统应保留待核对事项并给出中文保守说明，不应为了填满字段而生成英文摘要、重复小标题或没有来源的量化数字。\n\n"
                "## 关键词\n- PDE\n- PINN\n"
            ),
            model="MiniMax-M2.7",
            usage={"total_tokens": 420},
            raw={},
        )
        paper = Paper(title="Heading Cleanup")

        rendered = _generate_ai_light_profile(paper, "abstract text", ["PDE"])

        self.assertNotRegex(rendered["background"], r"(?m)^#{1,6}\s*研究背景\s*$")
        self.assertNotRegex(rendered["method"], r"(?m)^#{1,6}\s*方法原理\s*$")
        self.assertNotRegex(rendered["results"], r"(?m)^#{1,6}\s*主要结果\s*$")

    @patch("apps.papers.light_processing.call_minimax_chat")
    def test_legacy_ai_json_uses_quality_gate_and_normalizes_keywords(self, mocked_chat) -> None:
        mocked_chat.return_value = MiniMaxResponse(
            content=(
                '{"keywords":["Physics-Informed Neural Network","pinn","PDE"],'
                '"background":"背景太短。","method":"方法太短。","results":"结果太短。"}'
            ),
            model="MiniMax-M2.7",
            usage={"total_tokens": 80},
            raw={},
        )
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="Physics Informed Operators", source_pdf_path="quarantine/uploads/sample.pdf")
            task = TaskRecord.objects.create(
                task_type="paper_ai_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                run_paper_light_process_task.run(paper.id, task.id, True)

        profile = paper.light_profiles.get(is_active=True)
        self.assertEqual(profile.keywords, ["PINN", "PDE"])
        self.assertIn("当前粗读只能从题名", profile.background)
        self.assertIn("粗读筛选", profile.method)
        self.assertIn("深度处理", profile.results)
        for field in [profile.background, profile.method, profile.results]:
            self.assertGreaterEqual(len(field), 120)
            self.assertGreaterEqual(field.count(".") + field.count("\u3002"), 2)

    def test_downloads_uploaded_pdf(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="Downloadable paper", source_pdf_path="quarantine/uploads/sample.pdf")

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.get(f"/api/papers/{paper.id}/pdf/")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertIn("inline", response["Content-Disposition"])
            self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
            response.close()

    def test_download_filename_uses_current_title_not_stale_slug(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(title="Paper upload", source_pdf_path="quarantine/uploads/sample.pdf")
            paper.title = "Fourier Neural Operator for Parametric PDEs"
            paper.save(update_fields=["title", "updated_at"])

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.get(f"/api/papers/{paper.id}/pdf/?download=1")

            self.assertEqual(response.status_code, 200)
            try:
                self.assertIn("attachment", response["Content-Disposition"])
                self.assertIn("fourier-neural-operator-for-parametric-pdes.pdf", response["Content-Disposition"])
                self.assertNotIn("paper-upload.pdf", response["Content-Disposition"])
            finally:
                response.close()

    def test_keyword_aliases_are_serialized_once(self) -> None:
        pinn = Keyword.objects.create(name="PINN")
        long_name = Keyword.objects.create(name="Physics-Informed Neural Network")
        paper = Paper.objects.create(title="Keyword normalization")
        paper.keywords.set([pinn, long_name])

        response = self.client.get(f"/api/papers/{paper.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["keywords"], ["PINN"])

    def test_light_process_preserves_curated_existing_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(
                sample_pdf_bytes_with_metadata(
                    {
                        "/Title": "Extracted Metadata Title Should Not Win",
                        "/Author": "Metadata Author",
                        "/Subject": "Extracted abstract should not replace curated abstract.",
                        "/CreationDate": "D:20240101000000Z",
                        "/doi": "10.1234/extracted",
                    }
                )
            )
            paper = Paper.objects.create(
                title="Curated Paper Title",
                authors=["Curated Author"],
                year=2022,
                abstract="Curated abstract.",
                doi="10.9999/curated",
                arxiv_id="2201.00001",
                source_url="https://example.org/curated",
                source_pdf_path="quarantine/uploads/sample.pdf",
            )
            task = TaskRecord.objects.create(
                task_type="paper_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                run_paper_light_process_task.run(paper.id, task.id, False)

            paper.refresh_from_db()
            self.assertEqual(paper.title, "Curated Paper Title")
            self.assertEqual(paper.authors, ["Curated Author"])
            self.assertEqual(paper.year, 2022)
            self.assertEqual(paper.abstract, "Curated abstract.")
            self.assertEqual(paper.doi, "10.9999/curated")
            self.assertEqual(paper.arxiv_id, "2201.00001")
            self.assertEqual(paper.source_url, "https://example.org/curated")

    @patch("apps.papers.light_processing.extract_pdf_metadata")
    def test_light_worker_failure_restores_active_light_profile_status(self, mocked_extract_metadata) -> None:
        mocked_extract_metadata.side_effect = RuntimeError("parser crashed")
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/sample.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(
                title="PINNsFormer",
                source_pdf_path="quarantine/uploads/sample.pdf",
                status=Paper.Status.LIGHT_READY,
            )
            profile = PaperLightProfile.objects.create(
                paper=paper,
                version=1,
                is_active=True,
                background="existing",
                method="existing",
                results="existing",
            )
            task = TaskRecord.objects.create(
                task_type="paper_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)), self.assertRaises(RuntimeError):
                run_paper_light_process_task.run(paper.id, task.id, False)

        paper.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(paper.status, Paper.Status.LIGHT_READY)
        self.assertEqual(task.status, TaskRecord.Status.FAILED)
        self.assertEqual(task.result["paper_id"], paper.id)
        self.assertEqual(task.result["original_paper_status"], Paper.Status.LIGHT_READY)
        self.assertEqual(task.result["restored_paper_status"], Paper.Status.LIGHT_READY)
        self.assertEqual(task.result["active_light_profile_id"], profile.id)

    @patch("apps.papers.light_processing.extract_pdf_metadata")
    def test_light_worker_failure_sanitizes_paths_in_task_error_and_result(self, mocked_extract_metadata) -> None:
        mocked_extract_metadata.side_effect = RuntimeError(
            r"failed to read C:\secret\file.pdf copied from quarantine/uploads/private.pdf"
        )
        with TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "quarantine/uploads/private.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(sample_pdf_bytes())
            paper = Paper.objects.create(
                title="Private PDF",
                source_pdf_path="quarantine/uploads/private.pdf",
                status=Paper.Status.UPLOADED,
            )
            task = TaskRecord.objects.create(
                task_type="paper_light_process",
                status=TaskRecord.Status.PENDING,
                object_type="paper",
                object_id=paper.id,
                result={"original_paper_status": paper.status},
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)), self.assertRaises(RuntimeError):
                run_paper_light_process_task.run(paper.id, task.id, False)

        paper.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(paper.status, Paper.Status.NEEDS_REVIEW)
        self.assertEqual(task.result["original_paper_status"], Paper.Status.UPLOADED)
        self.assertNotIn(r"C:\secret\file.pdf", task.error)
        self.assertNotIn("quarantine/uploads/private.pdf", task.error)
        self.assertNotIn(r"C:\secret\file.pdf", task.result["error"])
        self.assertNotIn("quarantine/uploads/private.pdf", task.result["error"])
        self.assertIn("[path redacted]", task.error)
        self.assertIn("[storage key redacted]", task.result["error"])


class PaperMetadataAndOverviewUnitTests(SimpleTestCase):
    def test_extract_pdf_metadata_collects_citation_fields_and_arxiv_source(self) -> None:
        metadata = extract_pdf_metadata(
            sample_pdf_bytes_with_metadata(
                {
                    "/Title": "Physics Informed Neural Operators for Darcy Flow",
                    "/Author": "Alice Zhang; Bo Li and Carol Wang",
                    "/Subject": "We present a neural operator method for Darcy flow benchmarks.",
                    "/CreationDate": "D:20240203040506Z",
                    "/doi": "10.1234/example.darcy.2024",
                }
            ),
            filename="arXiv_2402.12345v2_main.pdf",
        )

        self.assertEqual(metadata.title, "Physics Informed Neural Operators for Darcy Flow")
        self.assertEqual(metadata.authors, ["Alice Zhang", "Bo Li", "Carol Wang"])
        self.assertEqual(metadata.year, 2024)
        self.assertEqual(metadata.doi, "10.1234/example.darcy.2024")
        self.assertEqual(metadata.arxiv_id, "2402.12345")
        self.assertEqual(metadata.source_url, "https://arxiv.org/abs/2402.12345")
        self.assertIn("neural operator method", metadata.abstract)

    def test_title_from_filename_removes_arxiv_download_noise_and_never_returns_numeric_only(self) -> None:
        title = title_from_filename("arXiv_2301.12345_download.pdf")

        self.assertEqual(title, "Paper 2301 12345")
        self.assertFalse(title.isdigit())
        self.assertNotIn("arxiv", title.lower())
        self.assertNotIn("download", title.lower())

    def test_pdf_metadata_rejects_noisy_pdf_header_as_title(self) -> None:
        noisy_title = (
            "Published as a conference paper at ICLR 2024 PINN SFORMER : A T RANSFORMER -BASED "
            "FRAME - WORK FOR PHYSICS -I NFORMED NEURAL NETWORKS Zhiyuan Zhao Georgia Institute of Technology "
            "Atlanta, GA 30332 leozhao1997@gatech.edu"
        )

        metadata = extract_pdf_metadata(sample_pdf_bytes_with_metadata({"/Title": noisy_title}))

        self.assertEqual(metadata.title, "Paper upload")
        self.assertNotIn("Published as a conference paper", metadata.title)

    def test_pdf_metadata_rejects_non_abstract_subject_text(self) -> None:
        metadata = extract_pdf_metadata(
            sample_pdf_bytes_with_metadata(
                {
                    "/Title": "Physics Informed Neural Operators for Darcy Flow",
                    "/Subject": (
                        "Computer Methods in Applied Mechanics and Engineering, Volume 430, 2024, "
                        "Article 117201. DOI: 10.1016/j.cma.2024.117201."
                    ),
                }
            )
        )

        self.assertEqual(metadata.abstract, "")

    def test_clean_ai_field_expands_too_short_values_with_stable_fallback(self) -> None:
        field = _clean_ai_field("", field_name="method", paper_title="Physics Informed Operators")

        self.assertGreaterEqual(len(field), 120)
        self.assertGreaterEqual(field.count(".") + field.count("\u3002"), 2)
        self.assertIn("方法原理", field)
