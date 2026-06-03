from __future__ import annotations

from django.urls import path

from apps.quality.views import QualityAuditEnqueueView, QualityIssueDetailView, QualityIssueListView


urlpatterns = [
    path("quality/issues/", QualityIssueListView.as_view(), name="quality-issue-list"),
    path("quality/issues/<int:pk>/", QualityIssueDetailView.as_view(), name="quality-issue-detail"),
    path("quality/audits/enqueue/", QualityAuditEnqueueView.as_view(), name="quality-audit-enqueue"),
]
