from __future__ import annotations

from dataclasses import dataclass

from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.library.models import KnowledgeSpace


@dataclass(frozen=True)
class KnowledgeSpaceMoveError(Exception):
    detail: str


def move_knowledge_space(
    *,
    space: KnowledgeSpace,
    parent_id: int | None | object = None,
    order: int | None = None,
    parent_provided: bool = False,
    order_provided: bool = False,
) -> KnowledgeSpace:
    if parent_provided:
        new_parent = None
        if parent_id not in (None, ""):
            new_parent = get_object_or_404(KnowledgeSpace, pk=parent_id, is_active=True)
        if space.would_create_cycle(new_parent):
            raise KnowledgeSpaceMoveError("Move would create a cycle in the knowledge tree.")
        space.parent = new_parent
    if order_provided and order is not None:
        space.order = order
    space.save()
    return space


def archive_knowledge_space(space: KnowledgeSpace) -> KnowledgeSpace:
    archive_ids = [space.id] + space.descendant_ids()
    KnowledgeSpace.objects.filter(id__in=archive_ids, is_active=True).update(
        is_active=False,
        updated_at=timezone.now(),
    )
    space.refresh_from_db()
    return space
