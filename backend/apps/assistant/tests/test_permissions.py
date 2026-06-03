from __future__ import annotations

from django.test import SimpleTestCase
from rest_framework.permissions import IsAuthenticated

from apps.assistant.views import AssistantMessageView, AssistantSessionDetailView, AssistantSessionListView


class AssistantPermissionTests(SimpleTestCase):
    def test_assistant_requires_login(self) -> None:
        for view_cls in [AssistantSessionListView, AssistantSessionDetailView, AssistantMessageView]:
            with self.subTest(view=view_cls.__name__):
                self.assertIsInstance(view_cls().get_permissions()[0], IsAuthenticated)
