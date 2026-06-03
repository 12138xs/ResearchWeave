from __future__ import annotations

from django.urls import path

from apps.documents.views import (
    DocumentDetailView,
    DocumentImportBatchDetailView,
    DocumentImportBatchEnqueueView,
    DocumentImportBatchListView,
    DocumentImportCandidateApproveView,
    DocumentImportCandidateDetailView,
    DocumentImportCandidateListView,
    DocumentListView,
)

urlpatterns = [
    path("documents/", DocumentListView.as_view(), name="document-list"),
    path("documents/<int:pk>/", DocumentDetailView.as_view(), name="document-detail"),
    path("document-import-batches/", DocumentImportBatchListView.as_view(), name="document-import-batch-list"),
    path(
        "document-import-batches/<int:pk>/",
        DocumentImportBatchDetailView.as_view(),
        name="document-import-batch-detail",
    ),
    path(
        "document-import-batches/<int:pk>/enqueue/",
        DocumentImportBatchEnqueueView.as_view(),
        name="document-import-batch-enqueue",
    ),
    path(
        "document-import-candidates/",
        DocumentImportCandidateListView.as_view(),
        name="document-import-candidate-list",
    ),
    path(
        "document-import-candidates/<int:pk>/",
        DocumentImportCandidateDetailView.as_view(),
        name="document-import-candidate-detail",
    ),
    path(
        "document-import-candidates/<int:pk>/approve/",
        DocumentImportCandidateApproveView.as_view(),
        name="document-import-candidate-approve",
    ),
]
