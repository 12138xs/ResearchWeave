from __future__ import annotations

import re

from django.db.models import Prefetch, Q

from apps.documents.models import Document, DocumentImportBatch, DocumentImportCandidate, DocumentVersion
from apps.library.models import KnowledgeSpace


def document_queryset(query_params, *, for_list: bool):
    queryset = Document.objects.select_related("space").prefetch_related("keywords")
    if for_list:
        queryset = queryset.prefetch_related(
            Prefetch(
                "versions",
                queryset=DocumentVersion.objects.filter(is_current=True).only(
                    "document_id",
                    "version",
                ),
                to_attr="current_versions_cache",
            )
        )
    else:
        queryset = queryset.prefetch_related("sources")

    query = query_params.get("q", "").strip()
    status = query_params.get("status", "").strip()
    space_param = query_params.get("space", "").strip()

    if query:
        query_filter = (
            Q(title__icontains=query)
            | Q(summary__icontains=query)
            | Q(keywords__name__icontains=query)
        )
        document_ids = document_ids_from_query(query)
        if document_ids:
            query_filter |= Q(id__in=document_ids)
        queryset = queryset.filter(query_filter).distinct()
    if status:
        queryset = queryset.filter(status=status)
    if space_param:
        if space_param == "ungrouped":
            return queryset.filter(space__isnull=True)
        selected_space = KnowledgeSpace.objects.filter(slug=space_param, is_active=True).first()
        if selected_space is None:
            space_id = parse_space_id(space_param)
            if space_id is not None:
                selected_space = KnowledgeSpace.objects.filter(pk=space_id, is_active=True).first()
        if selected_space is None:
            return queryset.none()
        space_ids = [selected_space.id]
        include_descendants = query_params.get("include_descendants", "").lower()
        if include_descendants in {"1", "true", "yes"}:
            space_ids.extend(selected_space.descendant_ids())
        queryset = queryset.filter(space_id__in=space_ids)
    return queryset


def document_import_batch_queryset():
    return DocumentImportBatch.objects.prefetch_related("sources", "candidates").all()


def document_import_candidate_queryset():
    return DocumentImportCandidate.objects.select_related(
        "batch",
        "source",
        "target_space",
        "document",
    )


def parse_space_id(value: str) -> int | None:
    if not value.isdigit() or len(value) > 18:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed <= 0:
        return None
    return parsed


def document_ids_from_query(query: str) -> list[int]:
    document_ids: list[int] = []
    for token in re.split(r"[\s,;，；、]+", query.strip()):
        normalized = token.strip().upper()
        if normalized.startswith("D"):
            normalized = normalized[1:]
        else:
            continue
        normalized = normalized.lstrip("0") or "0"
        if normalized.isdigit():
            document_id = int(normalized)
            if document_id > 0 and document_id not in document_ids:
                document_ids.append(document_id)
    return document_ids


def document_index_projection() -> list[dict[str, object]]:
    projections: list[dict[str, object]] = []
    queryset = Document.objects.select_related("space").prefetch_related(
        "keywords",
        Prefetch(
            "versions",
            queryset=DocumentVersion.objects.filter(is_current=True).only(
                "document_id",
                "markdown",
                "created_at",
            ),
            to_attr="current_version_cache",
        ),
    )
    for document in queryset:
        current_version = document.current_version_cache[0] if document.current_version_cache else None
        markdown = current_version.markdown if current_version is not None else ""
        source_updated_at = current_version.created_at if current_version is not None else document.updated_at
        projections.append(
            {
                "object_type": "document",
                "object_id": document.id,
                "title": document.title,
                "summary": document.summary,
                "body": markdown,
                "space_id": document.space_id,
                "keywords_json": [keyword.name for keyword in document.keywords.all()],
                "source_updated_at": source_updated_at,
            }
        )
    return projections
