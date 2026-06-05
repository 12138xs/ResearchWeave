from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.library.models import KnowledgeSpace


class CatalogApiTests(TestCase):
    def login_member(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        self.client.login(username="member", password="member-password")

    def test_catalog_stats_returns_empty_totals(self) -> None:
        response = self.client.get("/api/catalog/stats/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "papers": 0,
                "documents": 0,
                "knowledge_spaces": 0,
                "keywords": [],
                "status_counts": {},
            },
        )

    def test_papers_list_is_public_and_empty_initially(self) -> None:
        response = self.client.get("/api/papers/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_documents_list_is_public_and_empty_initially(self) -> None:
        response = self.client.get("/api/documents/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_can_create_nested_docs_knowledge_space(self) -> None:
        self.login_member()
        parent = KnowledgeSpace.objects.create(name="Linux 入门", kind=KnowledgeSpace.Kind.DOCS)

        response = self.client.post(
            "/api/knowledge-spaces/",
            {
                "name": "Shell 基础",
                "kind": "docs",
                "description": "命令行和脚本基础。",
                "parent_id": parent.id,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["name"], "Shell 基础")
        self.assertEqual(payload["kind"], "docs")
        self.assertEqual(payload["parent_id"], parent.id)
        self.assertEqual(KnowledgeSpace.objects.get(name="Shell 基础").parent, parent)
