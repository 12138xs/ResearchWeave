from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import reverse

from apps.papers.models import PaperReadingState, ReadingReview


class PaperReadingContractTests(SimpleTestCase):
    def test_reading_state_exposes_research_workflow_fields(self) -> None:
        field_names = {field.name for field in PaperReadingState._meta.fields}

        self.assertIn("paper", field_names)
        self.assertIn("reading_status", field_names)
        self.assertIn("reproduction_status", field_names)
        self.assertIn("owner", field_names)
        self.assertIn("next_step", field_names)
        self.assertIn("due_at", field_names)
        self.assertIn("updated_by", field_names)

        self.assertEqual(PaperReadingState.ReadingStatus.UNREAD, "unread")
        self.assertEqual(PaperReadingState.ReadingStatus.DISCUSSED, "discussed")
        self.assertEqual(PaperReadingState.ReproductionStatus.REPRODUCED, "reproduced")

    def test_reading_review_exposes_profile_review_fields(self) -> None:
        field_names = {field.name for field in ReadingReview._meta.fields}

        self.assertIn("paper", field_names)
        self.assertIn("profile_type", field_names)
        self.assertIn("profile_id", field_names)
        self.assertIn("status", field_names)
        self.assertIn("score", field_names)
        self.assertIn("notes", field_names)
        self.assertIn("reviewed_by", field_names)
        self.assertIn("reviewed_at", field_names)

        self.assertEqual(ReadingReview.ProfileType.LIGHT, "light")
        self.assertEqual(ReadingReview.ProfileType.DEEP, "deep")
        self.assertEqual(ReadingReview.Status.NEEDS_REVIEW, "needs_review")

    def test_reading_urls_are_named_and_nested_under_papers(self) -> None:
        self.assertEqual(reverse("paper-reading-state", kwargs={"pk": 1}), "/api/papers/1/reading-state/")
        self.assertEqual(reverse("paper-reading-review-list", kwargs={"pk": 1}), "/api/papers/1/reading-reviews/")
        self.assertEqual(
            reverse("paper-reading-review-detail", kwargs={"pk": 1, "review_id": 2}),
            "/api/papers/1/reading-reviews/2/",
        )
