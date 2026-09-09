"""Live source queries form the lexical baseline for later hybrid retrieval."""
import re
from collections import Counter

from django.db.models import Case, IntegerField, OuterRef, Q, Subquery, Value, When
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from apps.materials.models import Evidence, MaterialVersion
from apps.materials.selectors import materials


class EvidenceQuery(serializers.Serializer):
    q = serializers.CharField(max_length=500)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=50)
    material_id = serializers.IntegerField(required=False, min_value=1)
    mode = serializers.ChoiceField(choices=["keyword", "hybrid"], default="keyword")


def query_terms(query):
    terms = []
    for term in re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", query.casefold()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 2:
            terms.extend(term[index:index + 2] for index in range(len(term) - 1))
        else:
            terms.append(term)
    return list(dict.fromkeys(terms))[:32]


def excerpt(text, query, terms):
    lower = text.casefold()
    position = lower.find(query.casefold())
    if position < 0:
        positions = [lower.find(term) for term in terms if term in lower]
        position = min(positions) if positions else 0
    start = max(0, position - 100)
    return ("…" if start else "") + text[start:start + 600] + ("…" if start + 600 < len(text) else "")


def search_evidence(user, params):
    serializer = EvidenceQuery(data=params)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    query, limit = values["q"], values["limit"]
    terms = query_terms(query)
    if not terms:
        raise serializers.ValidationError("请输入文字或数字关键词。")
    allowed = materials(user)
    scoped = values.get("material_id")
    if scoped:
        get_object_or_404(allowed, pk=scoped)
        allowed = allowed.filter(pk=scoped)
    latest = MaterialVersion.objects.filter(material_id=OuterRef("version__material_id"),
        status__in=["ready", "needs_review"]).order_by("-number").values("pk")[:1]
    sources = Evidence.objects.filter(version__material_id__in=allowed.values("pk"),
        version_id=Subquery(latest)).exclude(text="").select_related("version__material")
    match = Q()
    rank = Value(0, output_field=IntegerField())
    for term in terms:
        text_match = Q(text__icontains=term)
        title_match = Q(version__material__title__icontains=term)
        match |= text_match | title_match
        rank = rank + Case(When(text_match, then=Value(10)), default=Value(0), output_field=IntegerField())
        rank = rank + Case(When(title_match, then=Value(4)), default=Value(0), output_field=IntegerField())
    rank = rank + Case(When(text__icontains=query, then=Value(30)), default=Value(0), output_field=IntegerField())
    candidates = list(sources.filter(match).annotate(score=rank).order_by("-score", "pk")[:501])
    counts, results = Counter(), []
    for row in candidates[:500]:
        version, material = row.version, row.version.material
        if counts[material.pk] >= (limit if scoped else 2):
            continue
        counts[material.pk] += 1
        url = f"/api/materials/{material.pk}/versions/{version.pk}/file/"
        results.append({
            "material_id": material.pk, "title": material.title, "version_id": version.pk,
            "version_number": version.number, "evidence_id": row.pk, "page": row.page,
            "line_start": row.line_start, "line_end": row.line_end,
            "review_required": row.review_required, "reviewed_at": row.reviewed_at,
            "excerpt": excerpt(row.text, query, terms), "score": row.score,
            "file_url": url + (f"#page={row.page}" if row.page else ""),
            "url": f"/materials/{material.pk}?version={version.pk}#evidence-{row.pk}",
        })
        if len(results) >= limit:
            break
    return {
        "mode": "keyword", "degraded": values["mode"] == "hybrid",
        "notice": "向量检索尚未接通，当前按关键词匹配原文证据。",
        "candidate_limit_reached": len(candidates) > 500,
        "results": results,
    }
