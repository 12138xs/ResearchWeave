from __future__ import annotations

from django.test import SimpleTestCase
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.quality.views import QualityAuditEnqueueView, QualityIssueDetailView, QualityIssueListView


class QualityPermissionTests(SimpleTestCase):
    def test_issue_read_is_public_and_writes_require_login(self) -> None:
        self.assertIsInstance(QualityIssueListView().get_permissions()[0], AllowAny)
        self.assertIsInstance(QualityIssueDetailView().get_permissions()[0], IsAuthenticated)
        self.assertIsInstance(QualityAuditEnqueueView().get_permissions()[0], IsAuthenticated)
