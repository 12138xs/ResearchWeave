from __future__ import annotations

from django.utils import timezone


def validate_annotation_anchors(*, paper, deep_profile=None, reason: str = "") -> dict[str, object]:
    annotations_manager = getattr(paper, "annotations", None)
    if annotations_manager is None:
        return {
            "paper_id": paper.id,
            "deep_profile_id": getattr(deep_profile, "id", None),
            "reason": reason,
            "checked_count": 0,
            "active_count": 0,
            "fuzzy_matched_count": 0,
            "orphaned_count": 0,
            "skipped": True,
            "validated_at": timezone.now().isoformat(),
        }

    annotations = list(annotations_manager.all())
    summary = {
        "paper_id": paper.id,
        "deep_profile_id": getattr(deep_profile, "id", None),
        "reason": reason,
        "checked_count": len(annotations),
        "active_count": 0,
        "fuzzy_matched_count": 0,
        "orphaned_count": 0,
        "skipped": False,
        "validated_at": timezone.now().isoformat(),
    }
    for annotation in annotations:
        status = getattr(annotation, "anchor_status", "active")
        if status == "active":
            summary["active_count"] += 1
        elif status == "fuzzy_matched":
            summary["fuzzy_matched_count"] += 1
        else:
            summary["orphaned_count"] += 1
    return summary
