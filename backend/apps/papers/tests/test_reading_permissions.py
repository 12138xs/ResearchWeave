from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.papers.views import PaperReadingReviewDetailView, PaperReadingReviewListView, PaperReadingStateView


class PaperReadingPermissionTests(SimpleTestCase):
    def assert_permission(self, view_cls, method: str, expected_type: type) -> None:
        view = view_cls()
        view.request = SimpleNamespace(method=method)
        permissions = view.get_permissions()
        self.assertEqual(len(permissions), 1)
        self.assertIsInstance(permissions[0], expected_type)

    def test_reading_reads_remain_public(self) -> None:
        self.assert_permission(PaperReadingStateView, "GET", AllowAny)
        self.assert_permission(PaperReadingReviewListView, "GET", AllowAny)

    def test_reading_writes_require_login(self) -> None:
        self.assert_permission(PaperReadingStateView, "PATCH", IsAuthenticated)
        self.assert_permission(PaperReadingReviewListView, "POST", IsAuthenticated)
        self.assert_permission(PaperReadingReviewDetailView, "PATCH", IsAuthenticated)
