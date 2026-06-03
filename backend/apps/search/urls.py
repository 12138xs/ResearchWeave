from __future__ import annotations

from django.urls import path

from apps.search.views import SearchReindexView, SearchView


urlpatterns = [
    path("search/", SearchView.as_view(), name="search-query"),
    path("search/reindex/", SearchReindexView.as_view(), name="search-reindex"),
]
