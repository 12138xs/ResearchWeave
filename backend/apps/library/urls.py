from __future__ import annotations

from django.urls import path

from apps.library.views import (
    CatalogStatsView,
    KeywordLibraryView,
    KeywordSuggestView,
    KnowledgeSpaceArchiveView,
    KnowledgeSpaceDetailView,
    KnowledgeSpaceListView,
    KnowledgeSpaceMoveView,
)

urlpatterns = [
    path("catalog/stats/", CatalogStatsView.as_view(), name="catalog-stats"),
    path("keywords/", KeywordLibraryView.as_view(), name="keyword-library"),
    path("keywords/suggest/", KeywordSuggestView.as_view(), name="keyword-suggest"),
    path("knowledge-spaces/", KnowledgeSpaceListView.as_view(), name="knowledge-space-list"),
    path(
        "knowledge-spaces/<int:pk>/",
        KnowledgeSpaceDetailView.as_view(),
        name="knowledge-space-detail",
    ),
    path(
        "knowledge-spaces/<int:pk>/move/",
        KnowledgeSpaceMoveView.as_view(),
        name="knowledge-space-move",
    ),
    path(
        "knowledge-spaces/<int:pk>/archive/",
        KnowledgeSpaceArchiveView.as_view(),
        name="knowledge-space-archive",
    ),
]
