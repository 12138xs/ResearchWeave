from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.annotations.validation import validate_annotation_anchors
from apps.papers.deep_processing import DeepProcessingUnavailable, DeepTaskPublishError, enqueue_deep_processing
from apps.papers.models import Paper, PaperDeepProfile
from apps.tasks.models import TaskRecord


def enqueue_deep_profile_task(paper: Paper, *, guidance: str = "") -> TaskRecord:
    return enqueue_deep_processing(paper, guidance=guidance)


def activate_deep_profile(paper: Paper, *, profile_id: int) -> tuple[PaperDeepProfile, list[PaperDeepProfile], dict]:
    target = get_object_or_404(paper.deep_profiles, pk=profile_id)
    with transaction.atomic():
        paper.deep_profiles.filter(is_active=True).exclude(pk=target.pk).update(is_active=False)
        if not target.is_active:
            target.is_active = True
            target.save(update_fields=["is_active"])
        paper.status = Paper.Status.DEEP_READY
        paper.save(update_fields=["status", "updated_at"])
    annotation_validation = validate_annotation_anchors(
        paper=paper,
        deep_profile=target,
        reason="manual_activation",
    )
    profiles = list(paper.deep_profiles.all())
    return target, profiles, annotation_validation


def delete_deep_profile(paper: Paper, *, profile_id: int) -> tuple[PaperDeepProfile | None, list[PaperDeepProfile]]:
    with transaction.atomic():
        locked_paper = Paper.objects.select_for_update().get(pk=paper.pk)
        target = get_object_or_404(locked_paper.deep_profiles.select_for_update(), pk=profile_id)
        deleted_was_active = target.is_active
        target.delete()

        remaining = list(locked_paper.deep_profiles.select_for_update().order_by("version", "created_at", "id"))
        for index, profile in enumerate(remaining, start=1):
            updates = []
            if profile.version != index:
                profile.version = index
                updates.append("version")
            if deleted_was_active:
                profile.is_active = False
                updates.append("is_active")
            if updates:
                profile.save(update_fields=updates)

        active = next((profile for profile in remaining if profile.is_active), None)
        if deleted_was_active and remaining:
            active = remaining[-1]
            active.is_active = True
            active.save(update_fields=["is_active"])

        if remaining:
            locked_paper.status = Paper.Status.DEEP_READY
        elif locked_paper.light_profiles.exists():
            locked_paper.status = Paper.Status.LIGHT_READY
        else:
            locked_paper.status = Paper.Status.UPLOADED
        locked_paper.save(update_fields=["status", "updated_at"])

        profiles = list(locked_paper.deep_profiles.all())
        active = next((profile for profile in profiles if profile.is_active), None)

    return active, profiles


__all__ = [
    "DeepProcessingUnavailable",
    "DeepTaskPublishError",
    "activate_deep_profile",
    "delete_deep_profile",
    "enqueue_deep_profile_task",
]
