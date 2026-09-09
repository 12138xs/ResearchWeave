from __future__ import annotations

from django.test import SimpleTestCase
from rest_framework.permissions import IsAuthenticated

from apps.search.views import SearchReindexView, SearchView


class SearchPermissionTests(SimpleTestCase):
    def test_search_read_requires_login_and_reindex_requires_login(self) -> None:
        self.assertIsInstance(SearchView().get_permissions()[0], IsAuthenticated)
        self.assertIsInstance(SearchReindexView().get_permissions()[0], IsAuthenticated)
