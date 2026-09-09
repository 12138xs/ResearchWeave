from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.documents.models import Document
from apps.library.keywords import canonical_keyword_names, get_or_create_canonical_keyword, prune_non_english_keywords
from apps.library.models import Keyword
from apps.papers.models import Paper


class KeywordApiTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="reader"))

    def test_keyword_library_groups_known_aliases(self) -> None:
        pinn = Keyword.objects.create(name="PINN")
        long_name = Keyword.objects.create(name="Physics-Informed Neural Network")
        pde = Keyword.objects.create(name="PDE")
        pdes = Keyword.objects.create(name="PDEs")
        transformer = Keyword.objects.create(name="Transformer")
        paper = Paper.objects.create(title="PINNsFormer")
        paper.keywords.set([pinn, long_name, pde, pdes, transformer])

        response = self.client.get("/api/keywords/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        pinn_entry = next(item for item in payload if item["name"] == "PINN")
        self.assertEqual(pinn_entry["paper_count"], 1)
        self.assertIn("Physics-Informed Neural Network", pinn_entry["aliases"])
        pde_entry = next(item for item in payload if item["name"] == "PDE")
        self.assertEqual(pde_entry["paper_count"], 1)
        self.assertIn("PDEs", pde_entry["aliases"])

    def test_keyword_suggest_returns_existing_keywords_only(self) -> None:
        pinn = Keyword.objects.create(name="PINN")
        transformer = Keyword.objects.create(name="Transformer")
        doc_only = Keyword.objects.create(name="PINN Docs")
        paper = Paper.objects.create(title="PINNsFormer")
        paper.keywords.set([pinn, transformer])
        doc = Document.objects.create(title="PINN Notes")
        doc.keywords.set([doc_only])

        response = self.client.get("/api/keywords/suggest/?q=pin")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["name"] for item in payload], ["PINN"])
        self.assertEqual(payload[0]["paper_count"], 1)

    def test_keyword_suggest_empty_query_returns_hot_keywords(self) -> None:
        pinn = Keyword.objects.create(name="PINN")
        transformer = Keyword.objects.create(name="Transformer")
        paper = Paper.objects.create(title="PINNsFormer")
        paper.keywords.set([pinn, transformer])

        response = self.client.get("/api/keywords/suggest/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["name"] for item in response.json()}, {"PINN", "Transformer"})

    def test_get_or_create_canonical_keyword_reuses_existing_normalized_name(self) -> None:
        existing = Keyword.objects.create(name="Conservation laws")

        keyword = get_or_create_canonical_keyword("conservation laws")

        self.assertEqual(keyword.id, existing.id)
        self.assertEqual(Keyword.objects.count(), 1)

    def test_canonical_keyword_names_keep_english_keywords_only(self) -> None:
        keywords = canonical_keyword_names(["PINN", "偏微分方程", "Navier-Stokes", "深度学习", "PDEs"])

        self.assertEqual(keywords, ["PINN", "Navier-Stokes", "PDE"])

    def test_canonical_keyword_names_deduplicate_markdown_and_known_aliases(self) -> None:
        keywords = canonical_keyword_names(
            [
                "**Graph Neural Networks**",
                "Graph Neural Network",
                "PDEs",
                "Partial Differential Equations",
                "PINNs",
                "Physics-Informed Neural Networks",
            ]
        )

        self.assertEqual(keywords, ["Graph Neural Networks", "PDE", "PINN"])

    def test_prune_non_english_keywords_removes_existing_links(self) -> None:
        chinese = Keyword.objects.create(name="偏微分方程")
        english = Keyword.objects.create(name="PDE")
        paper = Paper.objects.create(title="PDE Paper")
        doc = Document.objects.create(title="PDE Note")
        paper.keywords.set([chinese, english])
        doc.keywords.set([chinese])

        changes = prune_non_english_keywords()

        self.assertEqual(changes[0]["keyword"], "偏微分方程")
        self.assertFalse(Keyword.objects.filter(name="偏微分方程").exists())
        self.assertEqual(list(paper.keywords.values_list("name", flat=True)), ["PDE"])
        self.assertEqual(list(doc.keywords.values_list("name", flat=True)), [])

    def test_merge_known_aliases_reuses_existing_normalized_canonical_keyword(self) -> None:
        from apps.library.keywords import merge_known_keyword_aliases, normalize_keyword_text

        canonical = Keyword.objects.create(name="Finite Volume Method", normalized_name=normalize_keyword_text("Finite Volume Methods"))
        alias = Keyword.objects.create(name="FVM")
        paper = Paper.objects.create(title="Finite Volume Paper")
        paper.keywords.set([alias])

        changes = merge_known_keyword_aliases()

        self.assertEqual(changes[0]["alias"], "FVM")
        self.assertEqual(Keyword.objects.filter(normalized_name=normalize_keyword_text("Finite Volume Methods")).count(), 1)
        self.assertEqual(list(paper.keywords.values_list("id", flat=True)), [canonical.id])
