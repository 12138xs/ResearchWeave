from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.ai.models import PaperQAExchange
from apps.documents.models import Document
from apps.library.models import Keyword
from apps.papers.models import Paper, PaperDeepProfile, PaperLightProfile
from apps.tasks.models import TaskRecord


class PaperDeleteTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="member", password="member-password")

    def test_anonymous_delete_is_rejected(self) -> None:
        paper = Paper.objects.create(title="Delete target")

        response = self.client.delete(f"/api/papers/{paper.id}/")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Paper.objects.filter(pk=paper.pk).exists())

    def test_delete_cleans_related_records_storage_keywords_and_releases_number(self) -> None:
        self.client.login(username=self.user.username, password="member-password")
        with TemporaryDirectory() as tmpdir:
            storage_root = Path(tmpdir)
            pdf_path = storage_root / "quarantine/uploads/delete-target.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n")

            first = Paper.objects.create(title="First paper")
            target = Paper.objects.create(
                title="Delete target",
                source_pdf_path="quarantine/uploads/delete-target.pdf",
                status=Paper.Status.DEEP_READY,
            )
            last = Paper.objects.create(title="Last paper")
            orphan_keyword = Keyword.objects.create(name="Delete Only")
            shared_keyword = Keyword.objects.create(name="Shared Keyword")
            document_keyword = Keyword.objects.create(name="Document Keyword")
            target.keywords.set([orphan_keyword, shared_keyword, document_keyword])
            last.keywords.set([shared_keyword])
            document = Document.objects.create(title="Document keeping keyword")
            document.keywords.set([document_keyword])

            PaperLightProfile.objects.create(paper=target, version=1, is_active=True, background="background")
            PaperDeepProfile.objects.create(paper=target, version=1, is_active=True, summary="deep")
            PaperQAExchange.objects.create(paper=target, question="q", answer="a", user=self.user)
            TaskRecord.objects.create(
                task_type="deep_process_paper",
                object_type="paper",
                object_id=target.id,
                status=TaskRecord.Status.SUCCESS,
            )
            other_task = TaskRecord.objects.create(
                task_type="document_import",
                object_type="document",
                object_id=document.id,
                status=TaskRecord.Status.SUCCESS,
            )

            with override_settings(STORAGE_ROOT=storage_root):
                response = self.client.delete(f"/api/papers/{target.id}/")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["deleted_id"], target.id)
            self.assertEqual(payload["removed_tasks"], 1)
            self.assertEqual(payload["removed_related"]["light_profiles"], 1)
            self.assertEqual(payload["removed_related"]["deep_profiles"], 1)
            self.assertEqual(payload["removed_related"]["qa_exchanges"], 1)
            self.assertIn("Delete Only", payload["removed_keywords"])
            self.assertFalse(pdf_path.exists())
            self.assertFalse(Paper.objects.filter(pk=target.pk).exists())
            self.assertFalse(PaperLightProfile.objects.filter(paper_id=target.id).exists())
            self.assertFalse(PaperDeepProfile.objects.filter(paper_id=target.id).exists())
            self.assertFalse(PaperQAExchange.objects.filter(paper_id=target.id).exists())
            self.assertFalse(TaskRecord.objects.filter(object_type="paper", object_id=target.id).exists())
            self.assertTrue(TaskRecord.objects.filter(pk=other_task.pk).exists())
            self.assertFalse(Keyword.objects.filter(pk=orphan_keyword.pk).exists())
            self.assertTrue(Keyword.objects.filter(pk=shared_keyword.pk).exists())
            self.assertTrue(Keyword.objects.filter(pk=document_keyword.pk).exists())

            list_response = self.client.get("/api/papers/search/?page_size=10")
            self.assertEqual(list_response.status_code, 200)
            codes_by_title = {paper["title"]: paper["code"] for paper in list_response.json()["results"]}
            self.assertEqual(codes_by_title[first.title], "P000001")
            self.assertEqual(codes_by_title[last.title], "P000002")
