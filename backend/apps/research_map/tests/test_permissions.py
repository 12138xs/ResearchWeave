from __future__ import annotations

from django.test import SimpleTestCase
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.research_map.views import KnowledgeSpaceMapGenerateView, KnowledgeSpaceMapView


class ResearchMapPermissionTests(SimpleTestCase):
    def test_map_read_is_public_and_generation_requires_login(self) -> None:
        self.assertIsInstance(KnowledgeSpaceMapView().get_permissions()[0], AllowAny)
        self.assertIsInstance(KnowledgeSpaceMapGenerateView().get_permissions()[0], IsAuthenticated)
