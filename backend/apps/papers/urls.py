from __future__ import annotations

from django.urls import path

from apps.papers.views import (
    PaperDeepProcessView,
    PaperDeepProfileActivateView,
    PaperDeepProfileDeleteView,
    PaperDeepProfileListView,
    PaperDetailView,
    PaperLightProcessView,
    PaperListView,
    PaperMetadataSuggestionView,
    PaperPdfView,
    PaperReadingReviewDetailView,
    PaperReadingReviewListView,
    PaperReadingStateView,
    PaperReferenceImportView,
    PaperSearchView,
    PaperUploadView,
)

urlpatterns = [
    path("papers/", PaperListView.as_view(), name="paper-list"),
    path("papers/search/", PaperSearchView.as_view(), name="paper-search"),
    path("papers/upload/", PaperUploadView.as_view(), name="paper-upload"),
    path("papers/metadata-reference-candidates/", PaperReferenceImportView.as_view(), name="paper-reference-import"),
    path("papers/<int:pk>/light-process/", PaperLightProcessView.as_view(), name="paper-light-process"),
    path("papers/<int:pk>/metadata-suggestion/", PaperMetadataSuggestionView.as_view(), name="paper-metadata-suggestion"),
    path("papers/<int:pk>/reading-state/", PaperReadingStateView.as_view(), name="paper-reading-state"),
    path("papers/<int:pk>/reading-reviews/", PaperReadingReviewListView.as_view(), name="paper-reading-review-list"),
    path(
        "papers/<int:pk>/reading-reviews/<int:review_id>/",
        PaperReadingReviewDetailView.as_view(),
        name="paper-reading-review-detail",
    ),
    path("papers/<int:pk>/trigger-deep-process/", PaperDeepProcessView.as_view(), name="paper-deep-process"),
    path("papers/<int:pk>/deep-profiles/", PaperDeepProfileListView.as_view(), name="paper-deep-profiles"),
    path(
        "papers/<int:pk>/deep-profiles/<int:profile_id>/activate/",
        PaperDeepProfileActivateView.as_view(),
        name="paper-deep-profile-activate",
    ),
    path(
        "papers/<int:pk>/deep-profiles/<int:profile_id>/",
        PaperDeepProfileDeleteView.as_view(),
        name="paper-deep-profile-delete",
    ),
    path("papers/<int:pk>/pdf/", PaperPdfView.as_view(), name="paper-pdf"),
    path("papers/<int:pk>/", PaperDetailView.as_view(), name="paper-detail"),
]
