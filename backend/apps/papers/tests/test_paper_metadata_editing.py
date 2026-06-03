from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.library.models import Keyword
from apps.papers.models import Paper


class PaperMetadataEditingTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="member", password="member-password")
        self.paper = Paper.objects.create(
            title="PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks / ICLR / 2024",
            authors=[],
            year=None,
            venue="",
            abstract="",
        )

    def test_authenticated_user_can_update_title_and_metadata(self) -> None:
        self.client.login(username=self.user.username, password="member-password")

        response = self.client.patch(
            f"/api/papers/{self.paper.id}/",
            {
                "title": "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks",
                "authors": ["Zhao Zhiyuan", "Ding Xueying"],
                "publication_type": "conference",
                "year": 2024,
                "venue": "ICLR",
                "area": "Physics-informed neural networks",
                "abstract": "A transformer-based framework for physics-informed neural networks.",
                "doi": "10.48550/arXiv.2307.11833",
                "arxiv_id": "2307.11833",
                "source_url": "https://arxiv.org/abs/2307.11833",
                "code_status": "missing",
                "keywords": ["PINN", "Transformer", "PDE"],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["title"], "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks")
        self.assertEqual(payload["authors"], ["Zhao Zhiyuan", "Ding Xueying"])
        self.assertEqual(payload["year"], 2024)
        self.assertEqual(payload["venue"], "ICLR")
        self.assertEqual(payload["doi"], "10.48550/arXiv.2307.11833")
        self.assertEqual(payload["keywords"], ["PDE", "PINN", "Transformer"])

        self.paper.refresh_from_db()
        self.assertEqual(self.paper.title, "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks")
        self.assertEqual(self.paper.authors, ["Zhao Zhiyuan", "Ding Xueying"])
        self.assertEqual(set(self.paper.keywords.values_list("name", flat=True)), {"PINN", "Transformer", "PDE"})

    def test_patch_replaces_keywords_without_duplicates(self) -> None:
        Keyword.objects.create(name="PINN")
        self.paper.venue = "ICLR"
        self.paper.abstract = "Existing abstract should not be cleared by an unrelated partial update."
        self.paper.save(update_fields=["venue", "abstract"])
        self.paper.keywords.add(Keyword.objects.create(name="Old Keyword"))
        self.client.login(username=self.user.username, password="member-password")

        response = self.client.patch(
            f"/api/papers/{self.paper.id}/",
            {"keywords": ["pinn", "PINN", "Transformer"]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["keywords"], ["PINN", "Transformer"])
        self.paper.refresh_from_db()
        self.assertEqual(set(self.paper.keywords.values_list("name", flat=True)), {"PINN", "Transformer"})
        self.assertEqual(self.paper.venue, "ICLR")
        self.assertEqual(self.paper.abstract, "Existing abstract should not be cleared by an unrelated partial update.")

    def test_patch_normalizes_cleared_manual_metadata_fields(self) -> None:
        self.paper.keywords.add(Keyword.objects.create(name="Old Keyword"))
        self.client.login(username=self.user.username, password="member-password")

        response = self.client.patch(
            f"/api/papers/{self.paper.id}/",
            {
                "year": "",
                "venue": None,
                "volume": None,
                "issue": None,
                "pages": None,
                "area": None,
                "abstract": None,
                "doi": None,
                "arxiv_id": None,
                "source_url": None,
                "keywords": ["", None, "  PDE  "],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["year"])
        self.assertEqual(payload["source_url"], "")
        self.assertEqual(payload["venue"], "")
        self.assertEqual(payload["doi"], "")
        self.assertEqual(payload["keywords"], ["PDE"])

        self.paper.refresh_from_db()
        self.assertIsNone(self.paper.year)
        self.assertEqual(self.paper.source_url, "")
        self.assertEqual(set(self.paper.keywords.values_list("name", flat=True)), {"PDE"})

    def test_anonymous_user_cannot_patch_metadata(self) -> None:
        response = self.client.patch(
            f"/api/papers/{self.paper.id}/",
            {"title": "Should not change"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.paper.refresh_from_db()
        self.assertNotEqual(self.paper.title, "Should not change")
