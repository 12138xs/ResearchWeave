from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.documents.models import Document, DocumentSource, DocumentVersion
from apps.library.models import KnowledgeSpace


def results(payload):
    return payload["results"] if isinstance(payload, dict) and "results" in payload else payload


class DocumentSourceTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="reader"))

    def test_document_detail_includes_sources(self) -> None:
        document = Document.objects.create(title="Shell Basics", summary="Linux shell", status="published")
        DocumentVersion.objects.create(document=document, version=1, markdown="# Shell", is_current=True)
        DocumentSource.objects.create(
            document=document,
            source_type=DocumentSource.SourceType.URL,
            title="Bash Reference",
            url="https://example.com/bash",
            attribution="Example",
        )

        response = self.client.get(f"/api/documents/{document.id}/")

        self.assertEqual(response.status_code, 200)
        sources = response.json()["sources"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_type"], "url")
        self.assertEqual(sources[0]["title"], "Bash Reference")
        self.assertEqual(sources[0]["url"], "https://example.com/bash")
        self.assertEqual(sources[0]["attribution"], "Example")

    def test_document_serializes_stable_code_and_space_fields(self) -> None:
        root = KnowledgeSpace.objects.create(name="Linux", kind=KnowledgeSpace.Kind.DOCS)
        child = KnowledgeSpace.objects.create(name="Shell", kind=KnowledgeSpace.Kind.DOCS, parent=root)
        document = Document.objects.create(title="Shell Basics", space=child, status="published")
        DocumentVersion.objects.create(document=document, version=1, markdown="# Shell", is_current=True)

        response = self.client.get(f"/api/documents/{document.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["code"], f"D{document.id:06d}")
        self.assertEqual(payload["space"], "Shell")
        self.assertEqual(payload["space_id"], child.id)
        self.assertEqual(payload["space_slug"], child.slug)
        self.assertEqual(payload["space_path"], "Linux / Shell")

    def test_document_query_can_match_stable_code(self) -> None:
        document = Document.objects.create(title="Code Indexed Doc", status="published")
        other = Document.objects.create(title="Other Doc", status="published")
        DocumentVersion.objects.create(document=document, version=1, markdown="# Target", is_current=True)
        DocumentVersion.objects.create(document=other, version=1, markdown="# Other", is_current=True)

        response = self.client.get(f"/api/documents/?q=D{document.id:06d}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["title"] for item in results(response.json())], ["Code Indexed Doc"])

    def test_document_filter_includes_descendant_spaces(self) -> None:
        root = KnowledgeSpace.objects.create(name="Linux", kind=KnowledgeSpace.Kind.DOCS)
        child = KnowledgeSpace.objects.create(name="Shell", kind=KnowledgeSpace.Kind.DOCS, parent=root)
        root_doc = Document.objects.create(title="Linux Overview", space=root, status="published")
        child_doc = Document.objects.create(title="Shell Basics", space=child, status="published")
        DocumentVersion.objects.create(document=root_doc, version=1, markdown="# Linux", is_current=True)
        DocumentVersion.objects.create(document=child_doc, version=1, markdown="# Shell", is_current=True)

        response = self.client.get(f"/api/documents/?space={root.id}&include_descendants=1")

        self.assertEqual(response.status_code, 200)
        titles = {item["title"] for item in results(response.json())}
        self.assertEqual(titles, {"Linux Overview", "Shell Basics"})

    def test_document_filter_without_descendants_returns_direct_space_documents(self) -> None:
        root = KnowledgeSpace.objects.create(name="Linux", kind=KnowledgeSpace.Kind.DOCS)
        child = KnowledgeSpace.objects.create(name="Shell", kind=KnowledgeSpace.Kind.DOCS, parent=root)
        root_doc = Document.objects.create(title="Linux Overview", space=root, status="published")
        child_doc = Document.objects.create(title="Shell Basics", space=child, status="published")
        DocumentVersion.objects.create(document=root_doc, version=1, markdown="# Linux", is_current=True)
        DocumentVersion.objects.create(document=child_doc, version=1, markdown="# Shell", is_current=True)

        response = self.client.get(f"/api/documents/?space={root.id}")

        self.assertEqual(response.status_code, 200)
        titles = {item["title"] for item in results(response.json())}
        self.assertEqual(titles, {"Linux Overview"})

    def test_numeric_slug_takes_precedence_over_matching_id(self) -> None:
        slug_space = KnowledgeSpace.objects.create(
            name="Numeric Slug",
            slug="123",
            kind=KnowledgeSpace.Kind.DOCS,
        )
        id_space = KnowledgeSpace.objects.create(
            id=123,
            name="Id Space",
            slug="id-space",
            kind=KnowledgeSpace.Kind.DOCS,
        )
        slug_document = Document.objects.create(title="Slug Space Doc", space=slug_space, status="published")
        id_document = Document.objects.create(title="Id Space Doc", space=id_space, status="published")
        DocumentVersion.objects.create(document=slug_document, version=1, markdown="# Slug", is_current=True)
        DocumentVersion.objects.create(document=id_document, version=1, markdown="# Id", is_current=True)

        response = self.client.get("/api/documents/?space=123")

        self.assertEqual(response.status_code, 200)
        titles = {item["title"] for item in results(response.json())}
        self.assertEqual(titles, {"Slug Space Doc"})

    def test_oversized_numeric_space_filter_returns_empty_list(self) -> None:
        document = Document.objects.create(title="Unrelated Doc", status="published")
        DocumentVersion.objects.create(document=document, version=1, markdown="# Doc", is_current=True)

        response = self.client.get("/api/documents/?space=999999999999999999999999999999999999999")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(results(response.json()), [])

    def test_document_source_string_uses_title_url_or_source_type(self) -> None:
        titled_source = DocumentSource.objects.create(
            source_type=DocumentSource.SourceType.URL,
            title="Bash Reference",
            url="https://example.com/bash",
        )
        url_source = DocumentSource.objects.create(
            source_type=DocumentSource.SourceType.URL,
            url="https://example.com/linux",
        )
        typed_source = DocumentSource.objects.create(source_type=DocumentSource.SourceType.MANUAL)

        self.assertEqual(str(titled_source), "Bash Reference")
        self.assertEqual(str(url_source), "https://example.com/linux")
        self.assertEqual(str(typed_source), "manual")
