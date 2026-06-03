from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.ai.minimax import MiniMaxResponse
from apps.papers.models import Paper


class PaperMetadataCompletionTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="member", password="member-password")
        self.paper = Paper.objects.create(
            title="PINNsFormer",
            year=None,
            venue="",
            abstract="",
            arxiv_id="2307.11833",
            source_url="https://arxiv.org/abs/2307.11833",
        )

    @override_settings(WEB_SEARCH_PROVIDER="configured")
    @patch("apps.papers.metadata_completion.run_metadata_web_search")
    @patch("apps.papers.metadata_completion.call_minimax_chat")
    def test_metadata_suggestion_returns_candidates_without_mutating_paper(self, mocked_chat, mocked_search) -> None:
        self.client.login(username=self.user.username, password="member-password")
        mocked_search.return_value = [
            {
                "title": "PINNsFormer paper page",
                "url": "https://arxiv.org/abs/2307.11833",
                "snippet": "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks. ICLR 2024.",
            }
        ]
        mocked_chat.return_value = MiniMaxResponse(
            content=(
                '{"title":"PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks",'
                '"authors":["Zhao Zhiyuan","Ding Xueying"],"year":2024,"venue":"ICLR",'
                '"doi":"","arxiv_id":"2307.11833","source_url":"https://arxiv.org/abs/2307.11833",'
                '"abstract":"A transformer-based framework for physics-informed neural networks.",'
                '"keywords":["PINN","Transformer","PDE"],"confidence":0.86,'
                '"notes":"Matched arXiv and venue signals."}'
            ),
            model="MiniMax-M2.7",
            usage={"total_tokens": 128},
            raw={},
        )

        response = self.client.post(f"/api/papers/{self.paper.id}/metadata-suggestion/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["provider"], "web_search+llm")
        self.assertEqual(payload["suggestions"]["year"], 2024)
        self.assertEqual(payload["suggestions"]["venue"], "ICLR")
        self.assertEqual(payload["suggestions"]["keywords"], ["PINN", "Transformer", "PDE"])
        self.assertEqual(payload["evidence"][0]["url"], "https://arxiv.org/abs/2307.11833")
        self.assertGreaterEqual(len(payload["candidates"]), 1)
        self.assertEqual(payload["candidates"][0]["source"], "llm_suggestion")
        self.assertEqual(payload["candidates"][0]["title"], "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks")
        self.paper.refresh_from_db()
        self.assertIsNone(self.paper.year)
        self.assertEqual(self.paper.venue, "")

    def test_builds_selectable_candidates_from_evidence(self) -> None:
        from apps.papers.metadata_completion import _candidate_papers_from_evidence

        candidates = _candidate_papers_from_evidence(
            [
                {
                    "title": "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks - arXiv",
                    "url": "https://arxiv.org/abs/2307.11833",
                    "snippet": "Published at ICLR 2024. DOI 10.48550/arXiv.2307.11833",
                }
            ],
            None,
        )

        self.assertEqual(candidates[0]["source"], "web_search")
        self.assertEqual(candidates[0]["arxiv_id"], "2307.11833")
        self.assertEqual(candidates[0]["year"], 2024)
        self.assertEqual(candidates[0]["venue"], "ICLR")
        self.assertEqual(candidates[0]["abstract"], "")

    def test_web_search_candidate_only_uses_snippet_as_abstract_when_explicit(self) -> None:
        from apps.papers.metadata_completion import _candidate_papers_from_evidence

        candidates = _candidate_papers_from_evidence(
            [
                {
                    "title": "Physics-informed neural operators - arXiv",
                    "url": "https://arxiv.org/abs/2402.12345",
                    "snippet": (
                        "Abstract: We present a physics-informed neural operator for parametric PDE "
                        "benchmarks. The method combines operator learning with residual constraints "
                        "and is evaluated on Darcy flow and wave propagation settings."
                    ),
                }
            ],
            None,
        )

        self.assertIn("physics-informed neural operator", candidates[0]["abstract"])

    def test_normalize_suggestions_rejects_non_abstract_text(self) -> None:
        from apps.papers.metadata_completion import _normalize_suggestions

        suggestions = _normalize_suggestions(
            {
                "title": "PINNsFormer",
                "abstract": (
                    "Published as a conference paper at ICLR 2024. PINNsFormer: A Transformer-Based "
                    "Framework For Physics-Informed Neural Networks. Zhiyuan Zhao, Xueying Ding."
                ),
                "confidence": 0.9,
            }
        )

        self.assertEqual(suggestions["abstract"], "")
        self.assertIn("abstract", suggestions["notes"].lower())

    @override_settings(WEB_SEARCH_PROVIDER="disabled")
    def test_metadata_suggestion_requires_configured_web_search(self) -> None:
        self.client.login(username=self.user.username, password="member-password")

        response = self.client.post(f"/api/papers/{self.paper.id}/metadata-suggestion/")

        self.assertEqual(response.status_code, 503)
        self.assertIn("detail", response.json())

    @override_settings(
        WEB_SEARCH_PROVIDER="searxng",
        WEB_SEARCH_ENDPOINT="https://search.local/search",
        WEB_SEARCH_TIMEOUT_SECONDS=3,
    )
    @patch("apps.papers.metadata_completion.request.urlopen")
    def test_searxng_search_requests_json_format(self, mocked_urlopen) -> None:
        from apps.papers.metadata_completion import run_metadata_web_search

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "results": [
                            {
                                "title": "PINNsFormer",
                                "url": "https://arxiv.org/abs/2307.11833",
                                "content": "PINNsFormer ICLR 2024",
                            }
                        ]
                    }
                ).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()

        results = run_metadata_web_search(self.paper)

        requested_url = mocked_urlopen.call_args.args[0].full_url
        self.assertIn("format=json", requested_url)
        self.assertIn("categories=science%2Cgeneral", requested_url)
        self.assertIn("q=arXiv%3A2307.11833", requested_url)
        self.assertEqual(results[0]["snippet"], "PINNsFormer ICLR 2024")

    @override_settings(
        WEB_SEARCH_PROVIDER="searxng",
        WEB_SEARCH_ENDPOINT="https://search.local/search",
        WEB_SEARCH_TIMEOUT_SECONDS=3,
    )
    @patch("apps.papers.metadata_completion.request.urlopen")
    def test_search_query_prioritizes_identifiers_before_title(self, mocked_urlopen) -> None:
        from apps.papers.metadata_completion import run_metadata_web_search

        self.paper.doi = "10.48550/arXiv.2307.11833"
        self.paper.title = "A fallback short title"
        self.paper.save(update_fields=["doi", "title"])

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"results": []}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()

        run_metadata_web_search(self.paper)

        requested_url = mocked_urlopen.call_args.args[0].full_url
        query = requested_url.split("q=", 1)[1].split("&", 1)[0]
        self.assertLess(query.find("arXiv%3A2307.11833"), query.find("DOI%3A10.48550"))
        self.assertLess(query.find("DOI%3A10.48550"), query.find("https%3A%2F%2Farxiv.org"))
        self.assertLess(query.find("https%3A%2F%2Farxiv.org"), query.find("A+fallback+short+title"))

    @override_settings(
        WEB_SEARCH_PROVIDER="searxng",
        WEB_SEARCH_ENDPOINT="https://search.local/search",
        WEB_SEARCH_TIMEOUT_SECONDS=3,
    )
    @patch("apps.papers.metadata_completion.request.urlopen")
    def test_search_query_uses_existing_metadata_and_ignores_placeholder_title(self, mocked_urlopen) -> None:
        from apps.papers.metadata_completion import run_metadata_web_search

        self.paper.title = "Paper upload"
        self.paper.authors = ["Nathan Lichtlé", "Alexi Canesse"]
        self.paper.year = 2026
        self.paper.venue = "ICLR"
        self.paper.abstract = "Neural finite volume methods solve hyperbolic conservation laws."
        self.paper.arxiv_id = ""
        self.paper.source_url = ""
        self.paper.save(update_fields=["title", "authors", "year", "venue", "abstract", "arxiv_id", "source_url"])

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"results": []}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()

        run_metadata_web_search(self.paper)

        requested_url = mocked_urlopen.call_args.args[0].full_url
        query = requested_url.split("q=", 1)[1].split("&", 1)[0]
        self.assertNotIn("Paper+upload", query)
        self.assertIn("Nathan+Licht", query)
        self.assertIn("Alexi+Canesse", query)
        self.assertIn("2026", query)
        self.assertIn("ICLR", query)
        self.assertIn("Neural+finite+volume", query)

    def test_normalizes_string_authors_keywords_and_noisy_title_from_model(self) -> None:
        from apps.papers.metadata_completion import _normalize_suggestions

        suggestions = _normalize_suggestions(
            {
                "title": "  Published as a conference paper at ICLR 2024 PINNSFORMER : A TRANSFORMER-BASED FRAMEWORK FOR PHYSICS-INFORMED NEURAL NETWORKS  ",
                "authors": "Zhiyuan Zhao, Xueying Ding; B. Aditya Prakash",
                "year": "2024",
                "venue": "ICLR",
                "keywords": "PINN, Transformer; PDE",
                "confidence": "0.8",
            }
        )

        self.assertEqual(suggestions["title"], "PINNSFORMER : A TRANSFORMER-BASED FRAMEWORK FOR PHYSICS-INFORMED NEURAL NETWORKS")
        self.assertEqual(suggestions["authors"], ["Zhiyuan Zhao", "Xueying Ding", "B. Aditya Prakash"])
        self.assertEqual(suggestions["keywords"], ["PINN", "Transformer", "PDE"])
        self.assertEqual(suggestions["year"], 2024)

    def test_minimax_prompt_requires_evidence_first_complete_metadata(self) -> None:
        from apps.papers.metadata_completion import _build_metadata_messages

        messages = _build_metadata_messages(
            self.paper,
            [
                {
                    "title": "arXiv page",
                    "url": "https://arxiv.org/abs/2307.11833",
                    "snippet": "Full title and abstract appear here.",
                }
            ],
        )

        prompt = "\n".join(message["content"] for message in messages)
        self.assertIn("evidence-first", prompt)
        self.assertIn("complete paper title", prompt)
        self.assertIn("complete abstract", prompt)
        self.assertIn("Do not place search snippets", prompt)
        self.assertIn("abstract-like evidence", prompt)
        self.assertIn("3-8 English academic keywords", prompt)
        self.assertIn("Do not output Chinese keywords", prompt)
        self.assertIn("do not invent", prompt)
        self.assertIn("title/url/snippet", prompt)
        self.assertIn("arXiv/DOI", prompt)
