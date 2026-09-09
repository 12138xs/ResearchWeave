from __future__ import annotations

from django.test import SimpleTestCase
from rest_framework.permissions import IsAuthenticated

from apps.research_map.views import KnowledgeSpaceMapGenerateView, KnowledgeSpaceMapView


class ResearchMapPermissionTests(SimpleTestCase):
    def test_map_read_requires_login_and_generation_requires_login(self) -> None:
        self.assertIsInstance(KnowledgeSpaceMapView().get_permissions()[0], IsAuthenticated)
        self.assertIsInstance(KnowledgeSpaceMapGenerateView().get_permissions()[0], IsAuthenticated)
