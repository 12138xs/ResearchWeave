from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import reverse

from apps.search.models import SearchIndexEntry


class SearchContractTests(SimpleTestCase):
    def test_search_index_entry_keeps_cross_domain_projection_fields(self) -> None:
        field_names = {field.name for field in SearchIndexEntry._meta.fields}

        for field_name in {
            "object_type",
            "object_id",
            "title",
            "summary",
            "body",
            "space_id",
            "keywords_json",
            "source_updated_at",
            "embedding",
            "indexed_at",
        }:
            self.assertIn(field_name, field_names)

        self.assertEqual(SearchIndexEntry.ObjectType.PAPER, "paper")
        self.assertEqual(SearchIndexEntry.ObjectType.EXPERIMENT, "experiment")

    def test_search_urls_are_public_query_and_authenticated_reindex(self) -> None:
        self.assertEqual(reverse("search-query"), "/api/search/")
        self.assertEqual(reverse("search-reindex"), "/api/search/reindex/")
