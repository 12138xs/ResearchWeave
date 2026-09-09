from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.permissions import IsAuthenticated

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
from apps.library.views import (
    KnowledgeSpaceArchiveView,
    KnowledgeSpaceDetailView,
    KnowledgeSpaceListView,
    KnowledgeSpaceMoveView,
)
from apps.storage.views import ImageAssetView, ImageUploadView


class WritePermissionTests(SimpleTestCase):
    def assert_permission(self, view_cls, method: str, expected_type: type) -> None:
        view = view_cls()
        view.request = SimpleNamespace(method=method)
        permissions = view.get_permissions()
        self.assertEqual(len(permissions), 1)
        self.assertIsInstance(permissions[0], expected_type)

    def test_document_reads_require_login(self) -> None:
        for view_cls in [
            DocumentListView,
            DocumentDetailView,
            DocumentImportBatchListView,
            DocumentImportBatchDetailView,
            DocumentImportCandidateListView,
            DocumentImportCandidateDetailView,
        ]:
            with self.subTest(view=view_cls.__name__):
                self.assert_permission(view_cls, "GET", IsAuthenticated)

    def test_document_writes_require_login(self) -> None:
        for view_cls, method in [
            (DocumentListView, "POST"),
            (DocumentDetailView, "PATCH"),
            (DocumentImportBatchListView, "POST"),
            (DocumentImportBatchDetailView, "PATCH"),
            (DocumentImportBatchEnqueueView, "POST"),
            (DocumentImportCandidateListView, "POST"),
            (DocumentImportCandidateDetailView, "PATCH"),
            (DocumentImportCandidateApproveView, "POST"),
        ]:
            with self.subTest(view=view_cls.__name__, method=method):
                self.assert_permission(view_cls, method, IsAuthenticated)

    def test_knowledge_space_reads_require_login(self) -> None:
        for view_cls in [KnowledgeSpaceListView, KnowledgeSpaceDetailView]:
            with self.subTest(view=view_cls.__name__):
                self.assert_permission(view_cls, "GET", IsAuthenticated)

    def test_knowledge_space_writes_require_login(self) -> None:
        for view_cls, method in [
            (KnowledgeSpaceListView, "POST"),
            (KnowledgeSpaceDetailView, "PATCH"),
            (KnowledgeSpaceMoveView, "POST"),
            (KnowledgeSpaceArchiveView, "POST"),
        ]:
            with self.subTest(view=view_cls.__name__, method=method):
                self.assert_permission(view_cls, method, IsAuthenticated)

    def test_image_reads_require_login_but_upload_requires_login(self) -> None:
        self.assert_permission(ImageAssetView, "GET", IsAuthenticated)
        self.assert_permission(ImageUploadView, "POST", IsAuthenticated)
