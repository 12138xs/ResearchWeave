"""Read-only, permission-aware excerpts; model output never defines a source."""
import hashlib

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from collections import Counter

from apps.documents.models import DocumentVersion
from apps.experiments.selectors import accessible_experiments
from apps.materials.models import Evidence
from apps.materials.selectors import materials
from apps.papers.models import Paper
from apps.search.evidence import query_terms, visible_evidence, ranked_candidates
from apps.assistant.models import PersonalEntry, ResearchPublication
from apps.assistant.workspace_selectors import publication_allowed


def _source_visible(source, user):
    kind, pk = source.get("type"), source.get("id")
    if not user or not user.is_authenticated:
        return False
    if kind == "material":
        return Evidence.objects.filter(pk=pk, version__material_id__in=materials(user).values("pk")).exists()
    if kind == "document":
        return DocumentVersion.objects.filter(pk=pk).exists()
    if kind == "paper":
        return Paper.objects.filter(pk=pk).exists()
    if kind == "experiment":
        return accessible_experiments(user).filter(pk=pk).exists()
    if kind == "personal_note":
        return PersonalEntry.objects.filter(pk=pk, owner=user, kind="note", enabled=True).exists()
    if kind == "publication":
        row = ResearchPublication.objects.filter(pk=pk).first()
        return bool(row and publication_allowed(row))
    return False


def _scoped(queryset, scope, key, id_field="pk", space_field="space_id"):
    if scope and key not in scope and "space_ids" not in scope:
        return queryset.none()
    if key in scope:
        queryset = queryset.filter(**{f"{id_field}__in": scope[key]})
    if "space_ids" in scope:
        queryset = queryset.filter(**{f"{space_field}__in": scope["space_ids"]})
    return queryset


def _matches(queryset, terms, fields):
    return ranked_candidates(queryset, " ".join(terms), [(field, 10 if index == 0 else 4) for index, field in enumerate(fields)])


def material_scope(user, scope):
    allowed = materials(user)
    if not scope:
        return allowed
    match = Q(pk__in=[])
    if "material_ids" in scope and "space_ids" not in scope:
        match |= Q(pk__in=scope["material_ids"])
    if "paper_ids" in scope or "space_ids" in scope:
        papers = _scoped(Paper.objects.all(), scope, "paper_ids")
        match |= Q(versions__legacy_links__paper_id__in=papers.values("pk"))
    return allowed.filter(match).distinct()


def source_payload(kind, pk, title, text, location, url="", source_kind="unclassified", **identity):
    return {"type": kind, "id": pk, "title": title, "location": location, "url": url,
            "source_kind": source_kind, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "excerpt": text, "text_start": 0, "text_end": len(text), "total_chars": len(text),
            "truncated": False, **identity}


def slice_source(source, start, budget):
    text = source["excerpt"]
    end = min(len(text), start + budget)
    return {**source, "excerpt": text[start:end], "text_start": start, "text_end": end,
            "truncated": start > 0 or end < len(text)}


def search_window(source, query, terms):
    text = source["excerpt"]
    if len(text) <= 600:
        return source
    # lower() preserves positions for ordinary scientific Latin/CJK text.
    position = text.lower().find(query.lower())
    if position < 0:
        position = min((text.lower().find(term.lower()) for term in terms if term.lower() in text.lower()), default=0)
    return slice_source(source, max(0, position - 100), 600)


def material_source(row):
    version = row.version
    location = f"版本 {version.number}，" + (f"第 {row.page} 页" if row.page else f"第 {row.line_start}–{row.line_end} 行")
    if row.review_required and not row.reviewed_at:
        location += "，提取内容待人工核对"
    return source_payload("material", row.pk, version.material.title, row.text, location,
        f"/materials/{version.material_id}?version={version.pk}#evidence-{row.pk}", version.material.source_kind,
        material_id=version.material_id, version_id=version.pk, version_number=version.number, version_sha256=version.sha256,
        ordinal=row.ordinal, page=row.page, line_start=row.line_start, line_end=row.line_end)


def resolve_source(source, user, scope=None):
    """Resolve a native fixed identity. Never accepts filesystem paths."""
    if not _source_visible(source, user):
        raise ValueError("来源已不可访问")
    kind, pk = source["type"], source["id"]
    if kind == "material":
        row = Evidence.objects.select_related("version__material").get(pk=pk)
        if row.version.status not in {"ready", "needs_review"} or (scope is not None and not material_scope(user, scope).filter(pk=row.version.material_id).exists()):
            raise ValueError("材料不在读取范围")
        current = material_source(row)
    elif kind == "document":
        row = DocumentVersion.objects.select_related("document").get(pk=pk)
        if scope is not None and not _scoped(DocumentVersion.objects.filter(pk=pk), scope, "document_ids", "document_id", "document__space_id").exists():
            raise ValueError("文档不在读取范围")
        current = source_payload(kind, pk, row.document.title, row.markdown, f"文档版本 {row.version}，引用时正文摘录")
    elif kind == "paper":
        row = Paper.objects.get(pk=pk)
        if scope is not None and not _scoped(Paper.objects.filter(pk=pk), scope, "paper_ids").exists():
            raise ValueError("论文不在读取范围")
        current = source_payload(kind, pk, row.title, row.abstract, "论文摘要，非全文；引用时快照", source_kind="paper_abstract")
    elif kind == "experiment":
        row = accessible_experiments(user).get(pk=pk)
        if scope is not None and not _scoped(accessible_experiments(user).filter(pk=pk), scope, "experiment_ids").exists():
            raise ValueError("实验不在读取范围")
        current = source_payload(kind, pk, row.title, row.objective + "\n" + row.protocol_markdown, "实验目标与方案，引用时快照", source_kind="experiment_plan")
    elif kind == "personal_note":
        if scope and pk not in scope.get("note_ids", []):
            raise ValueError("记录不在读取范围")
        row = PersonalEntry.objects.get(pk=pk)
        current = source_payload(kind, pk, row.title, row.body, "本人的研究记录，非发表论文；引用时快照", source_kind="human_record")
    elif kind == "publication":
        if scope:
            raise ValueError("共享记录不在读取范围")
        row = ResearchPublication.objects.get(pk=pk)
        current = source_payload(kind, pk, row.title, row.body, "成员明确发布的研究记录，非论文结论", source_kind="human_record")
    else:
        raise ValueError("来源类型不可读取")
    for field in ("sha256", "source_kind", "material_id", "version_id", "version_sha256", "ordinal"):
        if field == "source_kind" and kind != "material" and source.get(field) == "unclassified":
            continue  # Legacy snapshots predate native record classification.
        if field in source and source[field] != current.get(field):
            raise ValueError("来源内容、身份或版本已变化")
    return current


def source_allowed(source, user):
    if "sha256" not in source:
        return _source_visible(source, user)
    try:
        resolve_source(source, user)
        return True
    except (ValueError, ObjectDoesNotExist):
        return False


def _search_once(user, scope, query):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError("检索词必须为 1–500 字。")
    terms = query_terms(query)
    if not terms:
        return []
    rows = []

    def add(kind, pk, title, text, location, url="", source_kind="unclassified", score=0):
        if not text.strip():
            return
        rows.append(search_window(source_payload(kind, pk, title, text, location, url, source_kind, score=score), query, terms))

    evidence = visible_evidence(user).filter(version__material_id__in=material_scope(user, scope).values("pk"))
    counts, seen = Counter(), set()
    for row in ranked_candidates(evidence, query, [("text", 10), ("version__material__title", 4)]):
        identity = (row.version.sha256, row.ordinal)
        if identity in seen or counts[row.version.sha256] >= 2:
            continue
        seen.add(identity)
        counts[row.version.sha256] += 1
        rows.append(search_window({**material_source(row), "score": row.score}, query, terms))
        if len(rows) >= 8:
            break
    documents = _scoped(DocumentVersion.objects.filter(is_current=True).select_related("document"), scope,
                        "document_ids", "document_id", "document__space_id")
    for row in _matches(documents, terms, ["markdown", "document__title"])[:4]:
        add("document", row.pk, row.document.title, row.markdown, f"文档版本 {row.version}，引用时正文摘录", score=row.score)
    papers = _scoped(Paper.objects.all(), scope, "paper_ids")
    for row in _matches(papers, terms, ["title", "abstract"])[:4]:
        add("paper", row.pk, row.title, row.abstract, "论文摘要，非全文；引用时快照", source_kind="paper_abstract", score=row.score)
    experiments = _scoped(accessible_experiments(user), scope, "experiment_ids")
    for row in _matches(experiments, terms, ["title", "objective", "protocol_markdown"])[:4]:
        add("experiment", row.pk, row.title, row.objective + "\n" + row.protocol_markdown,
            "实验目标与方案，引用时快照", source_kind="experiment_plan", score=row.score)
    if not scope or "note_ids" in scope:
        notes = PersonalEntry.objects.filter(owner=user, kind="note", enabled=True)
        if "note_ids" in scope:
            notes = notes.filter(pk__in=scope["note_ids"])
        for row in _matches(notes, terms, ["title", "body"])[:4]:
            add("personal_note", row.pk, row.title, row.body, "本人的研究记录，非发表论文；引用时快照", source_kind="human_record", score=row.score)
    if not scope:
        for row in _matches(ResearchPublication.objects.all(), terms, ["title", "body"])[:20]:
            if publication_allowed(row):
                add("publication", row.pk, row.title, row.body, "成员明确发布的研究记录，非论文结论", source_kind="human_record", score=row.score)
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows[:24]


def search_knowledge(user, scope, query, queries=None):
    if queries is not None and (not isinstance(queries, list) or len(queries) > 2):
        raise ValueError("最多附加两个检索变体")
    values = [query] + (queries or [])
    if any(not isinstance(value, str) or not value.strip() or len(value) > 500 for value in values):
        raise ValueError("检索词必须为 1–500 字")
    fused, scores, query_leaders = {}, Counter(), []
    for value in dict.fromkeys(values):
        for rank, row in enumerate(_search_once(user, scope, value), 1):
            key = (row["type"], row["id"])
            if rank == 1 and key not in query_leaders:
                query_leaders.append(key)
            # Keep the first concrete excerpt and fuse ranks; reads expose further text.
            fused.setdefault(key, row)
            scores[key] += 1 / (60 + rank)
    result, counts, seen = [], Counter(), set()
    for key in query_leaders + [key for key in sorted(fused, key=lambda key: -scores[key]) if key not in query_leaders]:
        row = fused[key]
        group = ("material", row["version_sha256"]) if row["type"] == "material" else (row["type"], row["id"])
        identity = (*group, row.get("ordinal", 0))
        if identity in seen or counts[group] >= 2:
            continue
        seen.add(identity)
        counts[group] += 1
        result.append(row)
        if len(result) >= 8:
            break
    return result
