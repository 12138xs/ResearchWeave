from __future__ import annotations

import math
import re

from django.db.models import Q

from apps.library.keywords import canonical_keyword_name, keyword_query_names
from apps.library.models import Keyword
from apps.library.selectors import keyword_summary_entries
from apps.papers.models import Paper


def filtered_paper_queryset(query_params):
    queryset = Paper.objects.select_related("space").prefetch_related(
        "keywords",
        "light_profiles",
        "deep_profiles",
    )
    query = query_params.get("q", "").strip()
    status = query_params.get("status", "").strip()
    year = query_params.get("year", "").strip()
    space = query_params.get("space", "").strip()
    reading_status = query_params.get("reading_status", "").strip()
    reproduction_status = query_params.get("reproduction_status", "").strip()
    owner = query_params.get("owner", "").strip()
    required_keywords = [
        item.strip()
        for item in query_params.get("required_keywords", "").split(",")
        if item.strip()
    ]

    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(abstract__icontains=query)
            | Q(authors__icontains=query)
            | Q(keywords__name__icontains=query)
            | Q(area__icontains=query)
            | Q(venue__icontains=query)
        ).distinct()
    if status:
        queryset = queryset.filter(status=status)
    if year.isdigit():
        queryset = queryset.filter(year=int(year))
    if space:
        space_filter = Q(space__slug=space)
        if space.isdigit():
            space_filter |= Q(space_id=int(space))
        queryset = queryset.filter(space_filter)
    if reading_status:
        queryset = queryset.filter(reading_state__reading_status=reading_status)
    if reproduction_status:
        queryset = queryset.filter(reading_state__reproduction_status=reproduction_status)
    if owner.isdigit():
        queryset = queryset.filter(reading_state__owner_id=int(owner))
    for keyword in required_keywords:
        queryset = queryset.filter(keywords__name__in=keyword_query_names(keyword))
    return queryset


def paper_search_context(query_params) -> tuple[dict[str, object], list[str]]:
    query = query_params.get("q", "").strip()
    status_value = query_params.get("status", "").strip()
    year_value = query_params.get("year", "").strip()
    reading_status = query_params.get("reading_status", "").strip()
    reproduction_status = query_params.get("reproduction_status", "").strip()
    owner = query_params.get("owner", "").strip()
    page = positive_int(query_params.get("page"), default=1, maximum=100000)
    page_size = positive_int(query_params.get("page_size"), default=25, maximum=100)
    requested_keywords = [
        item.strip()
        for item in query_params.get("keywords", "").split(",")
        if item.strip()
    ]

    exact_keywords, missing_keywords = resolve_existing_keywords(requested_keywords)
    if missing_keywords:
        return {}, missing_keywords

    queryset = Paper.objects.select_related("space").prefetch_related("keywords", "light_profiles", "deep_profiles")
    if status_value and status_value != "all":
        queryset = queryset.filter(status=status_value)
    if year_value.isdigit():
        queryset = queryset.filter(year=int(year_value))
    if reading_status:
        queryset = queryset.filter(reading_state__reading_status=reading_status)
    if reproduction_status:
        queryset = queryset.filter(reading_state__reproduction_status=reproduction_status)
    if owner.isdigit():
        queryset = queryset.filter(reading_state__owner_id=int(owner))
    for keyword in exact_keywords:
        queryset = queryset.filter(keywords__name__in=keyword_query_names(keyword))

    all_paper_ids = list(Paper.objects.order_by("id").values_list("id", flat=True))
    related_keywords = keyword_summary_entries(limit=8, query=query) if query else []
    if query:
        query_paper_ids = paper_ids_from_query(query, all_paper_ids)
        related_names = []
        for entry in related_keywords:
            related_names.extend(keyword_query_names(str(entry["name"])))
        query_filter = (
            Q(title__icontains=query)
            | Q(abstract__icontains=query)
            | Q(authors__icontains=query)
            | Q(area__icontains=query)
            | Q(venue__icontains=query)
        )
        if query_paper_ids:
            query_filter |= Q(id__in=query_paper_ids)
        if related_names:
            query_filter |= Q(keywords__name__in=related_names)
        queryset = queryset.filter(query_filter).distinct()

    papers = list(queryset)
    display_numbers = paper_display_number_map(papers)
    query_paper_ids = paper_ids_from_query(query, all_paper_ids) if query else []
    has_search_signal = bool(query or exact_keywords)
    if has_search_signal:
        papers.sort(
            key=lambda paper: (
                -paper_search_score(
                    paper,
                    query,
                    related_keywords,
                    query_paper_ids=query_paper_ids,
                    display_number=display_numbers.get(paper.id, paper.id),
                ),
                display_numbers.get(paper.id, paper.id),
                paper.title.lower(),
            )
        )
    else:
        papers.sort(key=lambda paper: display_numbers.get(paper.id, paper.id))

    count = len(papers)
    total_pages = max(1, math.ceil(count / page_size))
    page = min(page, total_pages)
    start = (page - 1) * page_size

    years = list(
        Paper.objects.exclude(year__isnull=True)
        .values_list("year", flat=True)
        .distinct()
        .order_by("-year")
    )
    return {
        "count": count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "page_items": papers[start : start + page_size],
        "paper_display_numbers": display_numbers,
        "related_keywords": related_keywords,
        "hot_keywords": keyword_summary_entries(limit=10),
        "years": years,
    }, []


def positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


def resolve_existing_keywords(values: list[str]) -> tuple[list[str], list[str]]:
    existing = set(Keyword.objects.values_list("name", flat=True))
    resolved: list[str] = []
    missing: list[str] = []
    for value in values:
        canonical = canonical_keyword_name(value)
        candidates = keyword_query_names(canonical)
        if any(candidate in existing for candidate in candidates):
            if canonical not in resolved:
                resolved.append(canonical)
        else:
            missing.append(value)
    return resolved, missing


def paper_ids_from_query(query: str, ordered_ids: list[int] | None = None) -> list[int]:
    paper_numbers: list[int] = []
    for token in re.split(r"[\s,;，；、]+", query.strip()):
        normalized = token.strip().upper()
        if normalized.startswith("P"):
            normalized = normalized[1:]
        normalized = normalized.lstrip("0") or "0"
        if normalized.isdigit():
            paper_number = int(normalized)
            if paper_number > 0 and paper_number not in paper_numbers:
                paper_numbers.append(paper_number)
    if not paper_numbers:
        return []
    if ordered_ids is None:
        ordered_ids = list(Paper.objects.order_by("id").values_list("id", flat=True))
    paper_ids: list[int] = []
    for paper_number in paper_numbers:
        index = paper_number - 1
        if 0 <= index < len(ordered_ids):
            paper_ids.append(ordered_ids[index])
    return paper_ids


def paper_search_score(
    paper: Paper,
    query: str,
    related_keywords: list[dict[str, object]],
    *,
    query_paper_ids: list[int] | None = None,
    display_number: int | None = None,
) -> int:
    if not query:
        return 0
    normalized = query.lower()
    if query_paper_ids is None:
        query_paper_ids = paper_ids_from_query(query)
    if display_number is None:
        display_number = paper.id
    if paper.id in query_paper_ids or f"p{display_number:06d}" in normalized:
        return 1000
    keyword_names = {keyword.name.lower() for keyword in paper.keywords.all()}
    related_names = {str(entry["name"]).lower() for entry in related_keywords}
    score = 0
    if keyword_names & related_names:
        score += 100
    if normalized in paper.title.lower():
        score += 50
    if normalized in " ".join(paper.authors).lower():
        score += 30
    if normalized in paper.venue.lower() or normalized in paper.area.lower():
        score += 20
    if normalized in paper.abstract.lower():
        score += 10
    return score


def paper_display_number_map(papers: list[Paper]) -> dict[int, int]:
    if not papers:
        return {}
    ids = {paper.id for paper in papers}
    return {
        paper_id: index + 1
        for index, paper_id in enumerate(Paper.objects.order_by("id").values_list("id", flat=True))
        if paper_id in ids
    }


def paper_index_projection() -> list[dict[str, object]]:
    projections: list[dict[str, object]] = []
    queryset = Paper.objects.select_related("space").prefetch_related(
        "keywords",
        "light_profiles",
        "deep_profiles",
    )
    for paper in queryset:
        active_light = next((profile for profile in paper.light_profiles.all() if profile.is_active), None)
        active_deep = next((profile for profile in paper.deep_profiles.all() if profile.is_active), None)
        body_parts = [
            paper.abstract,
            paper.area,
            paper.venue,
            " ".join(paper.authors),
        ]
        if active_light is not None:
            body_parts.extend([active_light.background, active_light.method, active_light.results])
        if active_deep is not None:
            body_parts.extend([active_deep.summary, active_deep.reproduction_notes])
        projections.append(
            {
                "object_type": "paper",
                "object_id": paper.id,
                "title": paper.title,
                "summary": paper.abstract[:1000],
                "body": "\n".join(part for part in body_parts if part),
                "space_id": paper.space_id,
                "keywords_json": [keyword.name for keyword in paper.keywords.all()],
                "source_updated_at": paper.updated_at,
            }
        )
    return projections
