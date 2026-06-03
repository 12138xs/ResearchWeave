from __future__ import annotations

from django.db.models import Count
from django.db.models.functions import Lower

from apps.documents.models import Document
from apps.library.keywords import CANONICAL_KEYWORD_ALIASES, canonical_keyword_name
from apps.library.models import Keyword, KnowledgeSpace
from apps.papers.models import Paper


def catalog_stats_payload() -> dict[str, object]:
    status_counts = dict(
        Paper.objects.values_list("status").annotate(total=Count("id")).order_by("status")
    )
    keywords = list(
        Keyword.objects.annotate(total=Count("papers") + Count("documents"))
        .filter(total__gt=0)
        .order_by("-total", "normalized_name")
        .values_list("name", flat=True)[:12]
    )
    return {
        "papers": Paper.objects.count(),
        "documents": Document.objects.count(),
        "knowledge_spaces": KnowledgeSpace.objects.filter(is_active=True).count(),
        "keywords": keywords,
        "status_counts": status_counts,
    }


def keyword_library_payload() -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for keyword in Keyword.objects.prefetch_related("papers", "documents"):
        canonical = canonical_keyword_name(keyword.name)
        entry = grouped.setdefault(
            canonical,
            {
                "name": canonical,
                "aliases": set(CANONICAL_KEYWORD_ALIASES.get(canonical, [])),
                "paper_ids": set(),
                "document_ids": set(),
                "source": "rule_based_v1",
            },
        )
        if keyword.name != canonical:
            entry["aliases"].add(keyword.name)
        entry["paper_ids"].update(keyword.papers.values_list("id", flat=True))
        entry["document_ids"].update(keyword.documents.values_list("id", flat=True))

    payload = []
    for entry in grouped.values():
        paper_ids = entry.pop("paper_ids")
        document_ids = entry.pop("document_ids")
        item = {
            "name": entry["name"],
            "aliases": sorted(entry["aliases"]),
            "paper_count": len(paper_ids),
            "document_count": len(document_ids),
            "total_count": len(paper_ids) + len(document_ids),
            "source": entry["source"],
        }
        if item["total_count"] > 0:
            payload.append(item)
    payload.sort(key=lambda item: (-item["total_count"], item["name"].lower()))
    return payload


def keyword_summary_entries(limit: int = 20, query: str = "") -> list[dict[str, object]]:
    entries = _keyword_entries()
    normalized_query = query.strip().lower()
    if normalized_query:
        entries = [
            entry
            for entry in entries
            if normalized_query in entry["name"].lower()
            or any(normalized_query in alias.lower() for alias in entry["aliases"])
        ]
    entries.sort(key=lambda item: (-item["paper_count"], item["name"].lower()))
    return entries[:limit]


def _keyword_entries() -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    queryset = (
        Keyword.objects.annotate(name_lower=Lower("name"))
        .prefetch_related("papers", "documents")
        .order_by("name_lower")
    )
    for keyword in queryset:
        canonical = canonical_keyword_name(keyword.name)
        entry = grouped.setdefault(
            canonical,
            {
                "name": canonical,
                "aliases": set(CANONICAL_KEYWORD_ALIASES.get(canonical, [])),
                "paper_ids": set(),
                "document_ids": set(),
            },
        )
        if keyword.name != canonical:
            entry["aliases"].add(keyword.name)
        entry["paper_ids"].update(keyword.papers.values_list("id", flat=True))
        entry["document_ids"].update(keyword.documents.values_list("id", flat=True))
    payload = []
    for entry in grouped.values():
        paper_ids = entry.pop("paper_ids")
        document_ids = entry.pop("document_ids")
        total_count = len(paper_ids) + len(document_ids)
        if len(paper_ids) == 0:
            continue
        payload.append(
            {
                "name": entry["name"],
                "aliases": sorted(entry["aliases"]),
                "paper_count": len(paper_ids),
                "document_count": len(document_ids),
                "total_count": total_count,
            }
        )
    return payload
