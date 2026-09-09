from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.documents.models import Document, DocumentSource, DocumentVersion
from apps.library.models import KnowledgeSpace


class DocumentPaginationTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="reader"))

    def test_list_returns_paginated_payload(self) -> None:
        source = DocumentSource.objects.create(source_type=DocumentSource.SourceType.MANUAL, title="Source")
        for index in range(30):
            document = Document.objects.create(title=f"Doc {index:02d}", status=Document.Status.PUBLISHED)
            document.sources.add(source)
            DocumentVersion.objects.create(
                document=document,
                version=1,
                markdown=f"# Doc {index:02d}\n\nLarge markdown body should stay out of list payload.",
                is_current=True,
            )

        response = self.client.get("/api/documents/?page=2&page_size=10")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 30)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 10)
        self.assertEqual(payload["total_pages"], 3)
        self.assertEqual(len(payload["results"]), 10)
        self.assertNotIn("markdown", payload["results"][0])
        self.assertNotIn("sources", payload["results"][0])
        self.assertEqual(payload["results"][0]["current_version"], 1)

    def test_list_filters_by_space_with_descendants_before_paginating(self) -> None:
        root = KnowledgeSpace.objects.create(name="Numerics", kind=KnowledgeSpace.Kind.DOCS)
        child = KnowledgeSpace.objects.create(
            name="Finite Difference",
            kind=KnowledgeSpace.Kind.DOCS,
            parent=root,
        )
        other = KnowledgeSpace.objects.create(name="Deep Learning", kind=KnowledgeSpace.Kind.DOCS)
        root_doc = Document.objects.create(title="Root Doc", space=root)
        child_doc = Document.objects.create(title="Child Doc", space=child)
        Document.objects.create(title="Other Doc", space=other)
        Document.objects.create(title="Ungrouped Doc")

        response = self.client.get(
            f"/api/documents/?space={root.id}&include_descendants=true&page=1&page_size=25"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            {item["id"] for item in payload["results"]},
            {root_doc.id, child_doc.id},
        )

    def test_list_filters_ungrouped_documents(self) -> None:
        space = KnowledgeSpace.objects.create(name="Numerics", kind=KnowledgeSpace.Kind.DOCS)
        Document.objects.create(title="Grouped Doc", space=space)
        ungrouped = Document.objects.create(title="Ungrouped Doc")

        response = self.client.get("/api/documents/?space=ungrouped&page=1&page_size=25")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["id"], ungrouped.id)
