from __future__ import annotations

import socket
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.documents.importing import (
    ParsedDraft,
    generate_candidate_from_text,
    is_safe_external_url,
    parse_ai_draft_payload,
)
from apps.documents.models import DocumentImportBatch, DocumentImportCandidate, DocumentSource
from apps.documents.tasks import generate_document_import_candidates


class ImportGenerationHelperTests(TestCase):
    @patch("apps.documents.importing.socket.getaddrinfo")
    def test_rejects_private_or_local_urls(self, mocked_getaddrinfo) -> None:
        def resolve(host: str, port):
            address_by_host = {
                "0.0.0.0": "0.0.0.0",
                "100.64.0.1": "100.64.0.1",
                "127.0.0.1": "127.0.0.1",
                "private-host.test": "192.168.1.10",
                "198.18.0.1": "198.18.0.1",
                "224.0.0.1": "224.0.0.1",
                "fc00::1": "fc00::1",
                "fe80::1": "fe80::1",
                "example.com": "93.184.216.34",
            }
            return [(None, None, None, "", (address_by_host[host], port))]

        mocked_getaddrinfo.side_effect = resolve

        self.assertFalse(is_safe_external_url("http://0.0.0.0/"))
        self.assertFalse(is_safe_external_url("http://100.64.0.1/"))
        self.assertFalse(is_safe_external_url("http://127.0.0.1:8000/admin"))
        self.assertFalse(is_safe_external_url("http://localhost:8000"))
        self.assertFalse(is_safe_external_url("http://private-host.test/"))
        self.assertFalse(is_safe_external_url("http://198.18.0.1/"))
        self.assertFalse(is_safe_external_url("http://224.0.0.1/"))
        self.assertFalse(is_safe_external_url("http://[fc00::1]/"))
        self.assertFalse(is_safe_external_url("http://[fe80::1]/"))
        self.assertTrue(is_safe_external_url("https://example.com/linux"))

    @patch("apps.documents.importing.socket.getaddrinfo")
    def test_rejects_ipv4_mapped_ipv6_private_urls(self, mocked_getaddrinfo) -> None:
        def resolve(host: str, port):
            address_by_host = {
                "mapped-loopback.test": "::ffff:127.0.0.1",
                "mapped-private.test": "::ffff:192.168.1.1",
                "mapped-shared.test": "::ffff:100.64.0.1",
            }
            return [(None, None, None, "", (address_by_host[host], port))]

        mocked_getaddrinfo.side_effect = resolve

        self.assertFalse(is_safe_external_url("https://mapped-loopback.test/resource"))
        self.assertFalse(is_safe_external_url("https://mapped-private.test/resource"))
        self.assertFalse(is_safe_external_url("https://mapped-shared.test/resource"))

    @patch("apps.documents.importing.socket.getaddrinfo")
    def test_rejects_non_http_scheme_and_dns_failures(self, mocked_getaddrinfo) -> None:
        mocked_getaddrinfo.side_effect = socket.gaierror("not found")

        self.assertFalse(is_safe_external_url("ftp://example.com/resource"))
        self.assertFalse(is_safe_external_url("https://missing.example.test/resource"))

    def test_parse_ai_draft_payload_accepts_structured_json(self) -> None:
        payload = {
            "title": "Linux Shell 入门",
            "summary": "介绍 shell 的基本概念。",
            "markdown": "# Linux Shell 入门\n\n## 核心概念\n\nShell 是命令解释器。",
            "keywords": ["Linux", "Shell"],
            "quality_notes": "资料完整。",
            "confidence": 0.82,
        }

        draft = parse_ai_draft_payload(payload)

        self.assertIsInstance(draft, ParsedDraft)
        self.assertEqual(draft.title, "Linux Shell 入门")
        self.assertEqual(draft.keywords, ["Linux", "Shell"])
        self.assertEqual(draft.confidence, 0.82)

    def test_parse_ai_draft_payload_rejects_missing_markdown(self) -> None:
        with self.assertRaises(ValueError):
            parse_ai_draft_payload({"title": "Bad", "summary": "", "keywords": []})

    @patch("apps.documents.importing.call_minimax_chat")
    def test_generate_candidate_from_text_parses_json_with_trailing_text(self, mocked_chat) -> None:
        mocked_chat.return_value = SimpleNamespace(
            content=(
                '{"title":"Linux Shell","summary":"Shell basics",'
                '"markdown":"# Linux Shell","keywords":["Linux"],'
                '"quality_notes":"Review citations.","confidence":0.7} trailing text'
            )
        )

        draft = generate_candidate_from_text("Linux Shell", "Shell is useful.", "Example")

        self.assertEqual(draft.title, "Linux Shell")
        self.assertEqual(draft.markdown, "# Linux Shell")
        self.assertEqual(draft.keywords, ["Linux"])
        self.assertEqual(draft.confidence, 0.7)


class DocumentImportBatchEnqueueTests(TestCase):
    def setUp(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        self.client.login(username="member", password="member-password")

    @patch("apps.documents.views.generate_document_import_candidates.delay")
    def test_enqueue_endpoint_marks_batch_queued_and_delays_task(self, mocked_delay) -> None:
        batch = DocumentImportBatch.objects.create(
            name="Linux links",
            source_mode=DocumentImportBatch.SourceMode.URLS,
        )

        response = self.client.post(f"/api/document-import-batches/{batch.id}/enqueue/")

        self.assertEqual(response.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.status, DocumentImportBatch.Status.QUEUED)
        mocked_delay.assert_called_once_with(batch.id)

    @patch("apps.documents.importing.socket.getaddrinfo")
    def test_import_batch_rejects_unsafe_url_sources(self, mocked_getaddrinfo) -> None:
        mocked_getaddrinfo.return_value = [(None, None, None, "", ("127.0.0.1", None))]

        response = self.client.post(
            "/api/document-import-batches/",
            {
                "name": "Unsafe URLs",
                "source_mode": DocumentImportBatch.SourceMode.URLS,
                "sources": [
                    {
                        "source_type": DocumentSource.SourceType.URL,
                        "url": "http://127.0.0.1:8000",
                        "title": "Local admin",
                    }
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(DocumentImportBatch.objects.count(), 0)
        self.assertEqual(DocumentSource.objects.count(), 0)


class DocumentImportCandidateGenerationTaskTests(TestCase):
    @patch("apps.documents.tasks.generate_candidate_from_text")
    def test_task_creates_review_candidate_and_marks_batch_needs_review(self, mocked_generate) -> None:
        batch = DocumentImportBatch.objects.create(
            name="Linux links",
            source_mode=DocumentImportBatch.SourceMode.URLS,
        )
        source = DocumentSource.objects.create(
            source_type=DocumentSource.SourceType.URL,
            title="Linux Shell",
            url="https://example.com/linux",
            raw_excerpt="Shell basics",
        )
        batch.sources.add(source)
        mocked_generate.return_value = ParsedDraft(
            title="Linux Shell",
            summary="Shell basics",
            markdown="# Linux Shell",
            keywords=["Linux", "Shell"],
            quality_notes="Review citations.",
            confidence=0.8,
        )

        result = generate_document_import_candidates(batch.id)

        self.assertEqual(result, {"created": 1})
        batch.refresh_from_db()
        self.assertEqual(batch.status, DocumentImportBatch.Status.NEEDS_REVIEW)
        candidate = DocumentImportCandidate.objects.get(batch=batch)
        self.assertEqual(candidate.source, source)
        self.assertEqual(candidate.proposed_title, "Linux Shell")
        self.assertEqual(candidate.proposed_markdown, "# Linux Shell")
        self.assertEqual(candidate.proposed_keywords, ["Linux", "Shell"])
        self.assertEqual(candidate.status, DocumentImportCandidate.Status.NEEDS_REVIEW)

    @patch("apps.documents.tasks.generate_candidate_from_text")
    def test_task_creates_fallback_candidate_when_ai_output_is_invalid(self, mocked_generate) -> None:
        batch = DocumentImportBatch.objects.create(
            name="External links",
            source_mode=DocumentImportBatch.SourceMode.URLS,
        )
        source = DocumentSource.objects.create(
            source_type=DocumentSource.SourceType.URL,
            title="Claude Code Hooks",
            url="https://example.com/hooks",
            raw_excerpt="Hooks can run checks before actions.",
            attribution="Example",
        )
        batch.sources.add(source)
        mocked_generate.side_effect = ValueError("AI draft response was not valid JSON.")

        result = generate_document_import_candidates(batch.id)

        self.assertEqual(result, {"created": 1})
        batch.refresh_from_db()
        self.assertEqual(batch.status, DocumentImportBatch.Status.NEEDS_REVIEW)
        candidate = DocumentImportCandidate.objects.get(batch=batch)
        self.assertEqual(candidate.proposed_title, "Claude Code Hooks")
        self.assertIn("Hooks can run checks", candidate.proposed_markdown)
        self.assertIn("AI 生成失败", candidate.quality_notes)
        self.assertEqual(candidate.confidence, 0.2)

    @patch("apps.documents.tasks.generate_candidate_from_text")
    def test_task_can_use_fallback_only_generation_mode(self, mocked_generate) -> None:
        batch = DocumentImportBatch.objects.create(
            name="Curated index",
            source_mode=DocumentImportBatch.SourceMode.URLS,
            options_json={"generation_mode": "fallback_only"},
        )
        source = DocumentSource.objects.create(
            source_type=DocumentSource.SourceType.URL,
            title="Claude Code Index",
            url="https://example.com/index",
            raw_excerpt="Curated directory entry.",
        )
        batch.sources.add(source)

        result = generate_document_import_candidates(batch.id)

        self.assertEqual(result, {"created": 1})
        mocked_generate.assert_not_called()
        candidate = DocumentImportCandidate.objects.get(batch=batch)
        self.assertEqual(candidate.proposed_title, "Claude Code Index")
        self.assertIn("Curated directory entry", candidate.proposed_markdown)
        self.assertIn("保底草稿", candidate.quality_notes)
