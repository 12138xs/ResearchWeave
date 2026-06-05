from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.documents.models import Document, DocumentVersion
from apps.library.models import Keyword, KnowledgeSpace


class DocumentEditorTests(TestCase):
    def setUp(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        self.client.login(username="member", password="member-password")

    def test_creates_markdown_document_with_initial_version_and_keywords(self) -> None:
        space = KnowledgeSpace.objects.create(name="Linux 入门", kind=KnowledgeSpace.Kind.DOCS)
        response = self.client.post(
            "/api/documents/",
            {
                "title": "Shell 基础",
                "summary": "常用 shell 命令整理。",
                "status": "published",
                "space_id": space.id,
                "keywords": ["Linux", "Shell"],
                "markdown": "# Shell 基础\n\nls、cd、grep 是最常用的入口。",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["title"], "Shell 基础")
        self.assertEqual(payload["current_version"], 1)
        self.assertEqual(payload["markdown"], "# Shell 基础\n\nls、cd、grep 是最常用的入口。")
        self.assertEqual(payload["keywords"], ["Linux", "Shell"])
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(DocumentVersion.objects.count(), 1)
        self.assertTrue(Keyword.objects.filter(name="Linux").exists())

    def test_updates_markdown_by_creating_new_current_version(self) -> None:
        document = Document.objects.create(title="Deep Learning Notes")
        DocumentVersion.objects.create(document=document, version=1, markdown="# Old", is_current=True)

        response = self.client.patch(
            f"/api/documents/{document.id}/",
            {
                "title": "深度学习入门",
                "summary": "从反向传播开始。",
                "keywords": ["Deep Learning"],
                "markdown": "# New\n\n反向传播是核心。",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["title"], "深度学习入门")
        self.assertEqual(payload["current_version"], 2)
        self.assertEqual(payload["markdown"], "# New\n\n反向传播是核心。")
        self.assertEqual(DocumentVersion.objects.filter(document=document).count(), 2)
        self.assertEqual(DocumentVersion.objects.get(document=document, is_current=True).version, 2)

    def test_detail_returns_current_markdown(self) -> None:
        document = Document.objects.create(title="Linux 网络")
        DocumentVersion.objects.create(document=document, version=1, markdown="# v1", is_current=False)
        DocumentVersion.objects.create(document=document, version=2, markdown="# v2", is_current=True)

        response = self.client.get(f"/api/documents/{document.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["markdown"], "# v2")
        self.assertEqual(response.json()["current_version"], 2)
