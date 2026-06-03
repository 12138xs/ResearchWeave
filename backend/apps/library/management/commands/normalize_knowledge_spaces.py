from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.documents.models import Document
from apps.library.models import KnowledgeSpace


SOURCE_SPACE_MARKERS = ("\u98de\u4e66", "\u6765\u6e90", "\u5bfc\u5165")
SOURCE_SPACE_TOKENS = {"feishu", "lark", "source", "import", "imports"}


@dataclass(frozen=True)
class SourceSpacePlan:
    space: KnowledgeSpace
    target_parent: KnowledgeSpace | None
    document_count: int


class Command(BaseCommand):
    help = "Identify and optionally archive source/import-like knowledge spaces."

    def add_arguments(self, parser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--dry-run",
            action="store_true",
            help="Show source/import-like spaces without changing data.",
        )
        mode.add_argument(
            "--apply",
            action="store_true",
            help="Move direct documents to the parent space, then mark source spaces inactive.",
        )

    def handle(self, *args, **options) -> None:
        apply = bool(options["apply"])
        dry_run = bool(options["dry_run"]) or not apply
        plans = find_source_space_plans()

        if not plans:
            self.stdout.write("No source/import-like knowledge spaces found.")
            return

        action = "Would normalize" if dry_run else "Normalizing"
        self.stdout.write(f"{action} {len(plans)} knowledge space(s):")
        for plan in plans:
            target = plan.target_parent.path_label() if plan.target_parent else "ungrouped"
            self.stdout.write(
                f"- #{plan.space.id} {plan.space.path_label()} "
                f"docs={plan.document_count} target={target} "
                f"reason=source/import is not a knowledge category"
            )

        if dry_run:
            return

        with transaction.atomic():
            now = timezone.now()
            for plan in plans:
                Document.objects.filter(space=plan.space).update(space=plan.target_parent, updated_at=now)
                KnowledgeSpace.objects.filter(pk=plan.space.pk, is_active=True).update(
                    is_active=False,
                    updated_at=now,
                )
        self.stdout.write("Applied normalization.")


def find_source_space_plans() -> list[SourceSpacePlan]:
    spaces = KnowledgeSpace.objects.filter(is_active=True).select_related("parent").order_by("id")
    plans: list[SourceSpacePlan] = []
    for space in spaces:
        if not _is_source_branch_space(space):
            continue
        target_parent = _nearest_category_parent(space)
        plans.append(
            SourceSpacePlan(
                space=space,
                target_parent=target_parent,
                document_count=Document.objects.filter(space=space).count(),
            )
        )
    return plans


def _is_source_like_space(space: KnowledgeSpace) -> bool:
    haystack = " ".join([space.name, space.slug, space.description]).lower()
    if any(marker in haystack for marker in SOURCE_SPACE_MARKERS):
        return True
    tokens = set(re.findall(r"[a-z0-9]+", haystack))
    return bool(tokens & SOURCE_SPACE_TOKENS)


def _nearest_category_parent(space: KnowledgeSpace) -> KnowledgeSpace | None:
    parent = space.parent
    while parent is not None:
        if parent.is_active and not _is_source_branch_space(parent):
            return parent
        parent = parent.parent
    return None


def _is_source_branch_space(space: KnowledgeSpace) -> bool:
    current: KnowledgeSpace | None = space
    while current is not None:
        if _is_source_like_space(current):
            return True
        current = current.parent
    return False
