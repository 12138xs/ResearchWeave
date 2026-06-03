from __future__ import annotations

from django.utils import timezone

from apps.papers.models import Paper, PaperReadingState, ReadingReview


def get_or_create_reading_state(paper: Paper) -> PaperReadingState:
    state, _ = PaperReadingState.objects.get_or_create(paper=paper)
    return state


def update_reading_state(paper: Paper, data: dict, *, user) -> PaperReadingState:
    state = get_or_create_reading_state(paper)
    for field in ("reading_status", "reproduction_status", "owner", "next_step", "due_at"):
        if field in data:
            setattr(state, field, data[field])
    state.updated_by = user if getattr(user, "is_authenticated", False) else None
    state.save()
    return state


def create_reading_review(paper: Paper, data: dict, *, user) -> ReadingReview:
    review = ReadingReview(
        paper=paper,
        profile_type=data["profile_type"],
        profile_id=data["profile_id"],
        status=data.get("status", ReadingReview.Status.NEEDS_REVIEW),
        score=data.get("score"),
        notes=data.get("notes", ""),
    )
    if getattr(user, "is_authenticated", False) and review.status != ReadingReview.Status.NEEDS_REVIEW:
        review.reviewed_by = user
        review.reviewed_at = timezone.now()
    review.save()
    return review


def update_reading_review(review: ReadingReview, data: dict, *, user) -> ReadingReview:
    status_changed = "status" in data and data["status"] != review.status
    for field in ("status", "score", "notes"):
        if field in data:
            setattr(review, field, data[field])
    if status_changed and getattr(user, "is_authenticated", False):
        review.reviewed_by = user
        review.reviewed_at = timezone.now()
    review.save()
    return review
