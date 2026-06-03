from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import reverse

from apps.quality.models import QualityIssue


class QualityContractTests(SimpleTestCase):
    def test_quality_issue_model_is_cross_domain_and_reviewable(self) -> None:
        field_names = {field.name for field in QualityIssue._meta.fields}

        for field_name in {
            "object_type",
            "object_id",
            "dimension",
            "severity",
            "status",
            "score",
            "notes",
            "evidence_json",
            "source_task",
            "reviewed_by",
            "reviewed_at",
        }:
            self.assertIn(field_name, field_names)

        self.assertEqual(QualityIssue.Dimension.AI_OUTPUT, "ai_output")
        self.assertEqual(QualityIssue.Status.OPEN, "open")

    def test_quality_urls_follow_issue_and_audit_shape(self) -> None:
        self.assertEqual(reverse("quality-issue-list"), "/api/quality/issues/")
        self.assertEqual(reverse("quality-issue-detail", kwargs={"pk": 1}), "/api/quality/issues/1/")
        self.assertEqual(reverse("quality-audit-enqueue"), "/api/quality/audits/enqueue/")
