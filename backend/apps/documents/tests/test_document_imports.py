from __future__ import annotations

from django.test import TestCase

from apps.documents.models import (
    Document,
    DocumentImportBatch,
    DocumentImportCandidate,
    DocumentSource,
    DocumentVersion,
)
from apps.library.models import KnowledgeSpace


class DocumentImportTests(TestCase):
    def test_create_import_batch_with_url_sources(self) -> None:
        space = KnowledgeSpace.objects.create(name="Linux", kind=KnowledgeSpace.Kind.DOCS)

        response = self.client.post(
            "/api/document-import-batches/",
            {
                "name": "Linux links",
                "source_mode": "urls",
                "target_space_id": space.id,
                "sources": [
                    {
                        "source_type": "url",
                        "url": "https://example.com/linux",
                        "title": "Linux",
                    }
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        batch = DocumentImportBatch.objects.get()
        self.assertEqual(batch.status, DocumentImportBatch.Status.DRAFT)
        self.assertEqual(batch.sources.count(), 1)

    def test_approve_candidate_creates_document(self) -> None:
        space = KnowledgeSpace.objects.create(name="Linux", kind=KnowledgeSpace.Kind.DOCS)
        batch = DocumentImportBatch.objects.create(
            name="Batch",
            source_mode=DocumentImportBatch.SourceMode.URLS,
            target_space=space,
        )
        source = DocumentSource.objects.create(
            source_type=DocumentSource.SourceType.URL,
            url="https://example.com/linux",
            title="Linux",
        )
        batch.sources.add(source)
        candidate = DocumentImportCandidate.objects.create(
            batch=batch,
            source=source,
            target_space=space,
            proposed_title="Linux Shell Basics",
            proposed_summary="Shell basics",
            proposed_markdown="# Linux Shell Basics\n\nShell is a command interpreter.",
            proposed_keywords=["Linux", "Shell"],
            status=DocumentImportCandidate.Status.NEEDS_REVIEW,
        )

        response = self.client.post(f"/api/document-import-candidates/{candidate.id}/approve/")

        self.assertEqual(response.status_code, 200)
        candidate.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(candidate.status, DocumentImportCandidate.Status.IMPORTED)
        self.assertIsNotNone(candidate.document)
        document = Document.objects.get(pk=candidate.document_id)
        self.assertEqual(document.title, "Linux Shell Basics")
        self.assertEqual(document.summary, "Shell basics")
        self.assertEqual(document.status, Document.Status.DRAFT)
        self.assertEqual(document.space, space)
        self.assertEqual(source.document, document)
        self.assertEqual(document.sources.first(), source)
        self.assertEqual(document.keywords.count(), 2)
        version = DocumentVersion.objects.get(document=document)
        self.assertEqual(version.version, 1)
        self.assertTrue(version.is_current)
        self.assertEqual(version.markdown, "# Linux Shell Basics\n\nShell is a command interpreter.")

    def test_reject_invalid_approval_status(self) -> None:
        batch = DocumentImportBatch.objects.create(
            name="Batch",
            source_mode=DocumentImportBatch.SourceMode.URLS,
        )
        candidate = DocumentImportCandidate.objects.create(
            batch=batch,
            proposed_title="Rejected Draft",
            proposed_markdown="# Rejected",
            status=DocumentImportCandidate.Status.REJECTED,
        )

        response = self.client.post(f"/api/document-import-candidates/{candidate.id}/approve/")

        self.assertEqual(response.status_code, 400)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, DocumentImportCandidate.Status.REJECTED)
        self.assertEqual(Document.objects.count(), 0)
        self.assertIsNone(candidate.document)

    def test_patch_candidate_status_is_read_only(self) -> None:
        batch = DocumentImportBatch.objects.create(
            name="Batch",
            source_mode=DocumentImportBatch.SourceMode.URLS,
        )
        candidate = DocumentImportCandidate.objects.create(
            batch=batch,
            proposed_title="Draft",
            proposed_markdown="# Draft",
        )

        response = self.client.patch(
            f"/api/document-import-candidates/{candidate.id}/",
            {"status": DocumentImportCandidate.Status.IMPORTED},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, DocumentImportCandidate.Status.DRAFT)

        response = self.client.patch(
            f"/api/document-import-candidates/{candidate.id}/",
            {"status": DocumentImportCandidate.Status.REJECTED},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, DocumentImportCandidate.Status.DRAFT)

    def test_approve_imported_candidate_does_not_duplicate_document(self) -> None:
        document = Document.objects.create(title="Existing Draft", status=Document.Status.DRAFT)
        batch = DocumentImportBatch.objects.create(
            name="Batch",
            source_mode=DocumentImportBatch.SourceMode.URLS,
        )
        candidate = DocumentImportCandidate.objects.create(
            batch=batch,
            proposed_title="Already Imported",
            proposed_markdown="# Already Imported",
            status=DocumentImportCandidate.Status.IMPORTED,
            document=document,
        )

        response = self.client.post(f"/api/document-import-candidates/{candidate.id}/approve/")

        self.assertEqual(response.status_code, 400)
        candidate.refresh_from_db()
        self.assertEqual(candidate.document, document)
        self.assertEqual(Document.objects.count(), 1)

    def test_candidate_list_invalid_batch_id_returns_empty_list(self) -> None:
        batch = DocumentImportBatch.objects.create(
            name="Batch",
            source_mode=DocumentImportBatch.SourceMode.URLS,
        )
        DocumentImportCandidate.objects.create(
            batch=batch,
            proposed_title="Draft",
            proposed_markdown="# Draft",
        )

        response = self.client.get("/api/document-import-candidates/?batch_id=abc")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
