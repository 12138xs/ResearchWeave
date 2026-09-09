from __future__ import annotations

from django.urls import path

from apps.search.views import AssistedEvidenceSearchView, EvidenceSearchView, SearchReindexView, SearchView


urlpatterns = [
    path("search/", SearchView.as_view(), name="search-query"),
    path("search/evidence/", EvidenceSearchView.as_view(), name="evidence-search"),
    path("search/evidence/assist/", AssistedEvidenceSearchView.as_view(), name="assisted-evidence-search"),
    path("search/reindex/", SearchReindexView.as_view(), name="search-reindex"),
]
