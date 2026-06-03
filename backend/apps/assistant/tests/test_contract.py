from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import reverse

from apps.assistant.models import AssistantExchange, AssistantSession


class AssistantContractTests(SimpleTestCase):
    def test_assistant_session_and_exchange_capture_scoped_sources(self) -> None:
        session_fields = {field.name for field in AssistantSession._meta.fields}
        exchange_fields = {field.name for field in AssistantExchange._meta.fields}

        for field_name in {"title", "mode", "scope_json", "created_by"}:
            self.assertIn(field_name, session_fields)

        for field_name in {"session", "question", "answer", "sources", "model", "usage", "context_warning"}:
            self.assertIn(field_name, exchange_fields)

        self.assertEqual(AssistantSession.Mode.COMPARE, "compare")
        self.assertEqual(AssistantSession.Mode.FREEFORM_SCOPED, "freeform_scoped")

    def test_assistant_urls_are_session_scoped(self) -> None:
        self.assertEqual(reverse("assistant-session-list"), "/api/assistant/sessions/")
        self.assertEqual(reverse("assistant-session-detail", kwargs={"pk": 1}), "/api/assistant/sessions/1/")
        self.assertEqual(
            reverse("assistant-session-message", kwargs={"pk": 1}),
            "/api/assistant/sessions/1/messages/",
        )
