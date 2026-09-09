from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.documents.models import Document
from apps.library.models import Keyword
from apps.papers.models import Paper


class PaperFilterTests(TestCase):
    def setUp(self) -> None:
        self.client.force_login(get_user_model().objects.create_user(username="reader"))
        self.pinn = Keyword.objects.create(name="PINN")
        self.transformer = Keyword.objects.create(name="Transformer")
        self.navier = Keyword.objects.create(name="Navier-Stokes")

        self.paper_a = Paper.objects.create(
            title="PINNsFormer for PDE Solving",
            year=2024,
            authors=["Alice Zhang", "Bo Li"],
            publication_type="conference",
            venue="NeurIPS",
            volume="37",
            issue="1",
            pages="100-112",
            source_url="https://example.org/pinnsformer",
        )
        self.paper_a.keywords.set([self.pinn, self.transformer])

        self.paper_b = Paper.objects.create(title="Neural Operator for Navier-Stokes", year=2023)
        self.paper_b.keywords.set([self.navier])

        self.paper_c = Paper.objects.create(title="Physics-Informed Neural Networks", year=2024)
        self.paper_c.keywords.set([self.pinn])

    def test_filters_by_year(self) -> None:
        response = self.client.get("/api/papers/?year=2023")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([paper["title"] for paper in response.json()], ["Neural Operator for Navier-Stokes"])

    def test_requires_all_selected_keywords(self) -> None:
        response = self.client.get("/api/papers/?required_keywords=PINN,Transformer")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([paper["title"] for paper in response.json()], ["PINNsFormer for PDE Solving"])

    def test_fuzzy_query_can_match_keywords(self) -> None:
        response = self.client.get("/api/papers/?q=navier")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([paper["title"] for paper in response.json()], ["Neural Operator for Navier-Stokes"])

    def test_serializes_citation_metadata(self) -> None:
        response = self.client.get("/api/papers/?required_keywords=PINN,Transformer")

        self.assertEqual(response.status_code, 200)
        paper = response.json()[0]
        self.assertEqual(paper["code"], "P000001")
        self.assertEqual(paper["authors"], ["Alice Zhang", "Bo Li"])
        self.assertEqual(paper["publication_type"], "conference")
        self.assertEqual(paper["venue"], "NeurIPS")
        self.assertEqual(paper["volume"], "37")
        self.assertEqual(paper["issue"], "1")
        self.assertEqual(paper["pages"], "100-112")
        self.assertEqual(paper["source_url"], "https://example.org/pinnsformer")

    def test_fuzzy_query_can_match_authors(self) -> None:
        response = self.client.get("/api/papers/?q=alice")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([paper["title"] for paper in response.json()], ["PINNsFormer for PDE Solving"])

    def test_search_endpoint_returns_paginated_results_and_facets(self) -> None:
        response = self.client.get("/api/papers/search/?page_size=2&page=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["page_size"], 2)
        self.assertEqual(payload["total_pages"], 2)
        self.assertEqual(len(payload["results"]), 2)
        self.assertIn(2024, payload["years"])
        self.assertIn("PINN", [item["name"] for item in payload["hot_keywords"]])

    def test_search_without_query_orders_by_display_number(self) -> None:
        response = self.client.get("/api/papers/search/?page_size=10")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [paper["title"] for paper in response.json()["results"]],
            [
                "PINNsFormer for PDE Solving",
                "Neural Operator for Navier-Stokes",
                "Physics-Informed Neural Networks",
            ],
        )

    def test_search_hot_keywords_returns_top_10_with_papers_only(self) -> None:
        doc_only = Keyword.objects.create(name="Docs Only")
        doc = Document.objects.create(title="Docs Only Note")
        doc.keywords.set([doc_only])
        for index in range(12):
            keyword = Keyword.objects.create(name=f"Paper Keyword {index:02d}")
            for paper_index in range(index + 1):
                paper = Paper.objects.create(title=f"Paper Keyword {index:02d} Study {paper_index:02d}")
                paper.keywords.set([keyword])

        response = self.client.get("/api/papers/search/?page_size=1")

        self.assertEqual(response.status_code, 200)
        hot_keywords = response.json()["hot_keywords"]
        self.assertEqual(len(hot_keywords), 10)
        self.assertNotIn("Docs Only", [item["name"] for item in hot_keywords])
        self.assertTrue(all(item["paper_count"] > 0 for item in hot_keywords))
        self.assertEqual(
            [item["name"] for item in hot_keywords[:3]],
            ["Paper Keyword 11", "Paper Keyword 10", "Paper Keyword 09"],
        )

    def test_search_caps_page_size_at_100(self) -> None:
        response = self.client.get("/api/papers/search/?page_size=500")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["page_size"], 100)

    def test_search_requires_existing_exact_keywords(self) -> None:
        response = self.client.get("/api/papers/search/?keywords=PINN,NotAKeyword")

        self.assertEqual(response.status_code, 400)
        self.assertIn("keywords", response.json())

    def test_search_filters_by_existing_exact_keywords(self) -> None:
        response = self.client.get("/api/papers/search/?keywords=PINN,Transformer")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([paper["title"] for paper in response.json()["results"]], ["PINNsFormer for PDE Solving"])

    def test_search_fuzzy_query_returns_related_keywords(self) -> None:
        response = self.client.get("/api/papers/search/?q=navier")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([paper["title"] for paper in payload["results"]], ["Neural Operator for Navier-Stokes"])
        self.assertEqual([item["name"] for item in payload["related_keywords"]], ["Navier-Stokes"])

    def test_search_can_match_stable_paper_number(self) -> None:
        response = self.client.get("/api/papers/search/?q=P000001")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([paper["title"] for paper in response.json()["results"]], ["PINNsFormer for PDE Solving"])

    def test_display_paper_number_is_released_after_delete(self) -> None:
        self.paper_b.delete()

        response = self.client.get("/api/papers/search/?page_size=10")

        self.assertEqual(response.status_code, 200)
        codes_by_title = {paper["title"]: paper["code"] for paper in response.json()["results"]}
        self.assertEqual(codes_by_title["PINNsFormer for PDE Solving"], "P000001")
        self.assertEqual(codes_by_title["Physics-Informed Neural Networks"], "P000002")
