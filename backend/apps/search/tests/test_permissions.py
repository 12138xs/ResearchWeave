from __future__ import annotations

from django.test import SimpleTestCase
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.search.views import SearchReindexView, SearchView


class SearchPermissionTests(SimpleTestCase):
    def test_search_read_is_public_and_reindex_requires_login(self) -> None:
        self.assertIsInstance(SearchView().get_permissions()[0], AllowAny)
        self.assertIsInstance(SearchReindexView().get_permissions()[0], IsAuthenticated)
