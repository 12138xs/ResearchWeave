from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.search.models import SearchIndexEntry


def search_entries(params) -> QuerySet[SearchIndexEntry]:
    queryset = SearchIndexEntry.objects.all()
    query = params.get("q", "").strip()
    scope = {
        item.strip()
        for item in params.get("scope", "").split(",")
        if item.strip()
    }
    space = params.get("space", "").strip()

    if scope:
        queryset = queryset.filter(object_type__in=scope)
    if space.isdigit():
        queryset = queryset.filter(space_id=int(space))
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(summary__icontains=query)
            | Q(body__icontains=query)
            | Q(keywords_json__icontains=query)
        )
    return queryset.order_by("-source_updated_at", "object_type", "title")
