"""Read-only, permission-aware excerpts; model output never defines a source."""
import hashlib

from django.db.models import Case, IntegerField, Q, Value, When

from apps.documents.models import DocumentVersion
from apps.experiments.selectors import accessible_experiments
from apps.materials.models import Evidence
from apps.materials.selectors import materials
from apps.papers.models import Paper
from apps.search.evidence import excerpt, query_terms, visible_evidence
from apps.assistant.models import PersonalEntry, ResearchPublication
from apps.assistant.workspace_selectors import publication_allowed


def source_allowed(source, user):
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
    match = Q()
    rank = Value(0, output_field=IntegerField())
    for term in terms:
        for field in fields:
            condition = Q(**{f"{field}__icontains": term})
            match |= condition
            rank = rank + Case(When(condition, then=Value(1)), default=Value(0), output_field=IntegerField())
    return queryset.filter(match).annotate(_relevance=rank).order_by("-_relevance", "pk")


def search_knowledge(user, scope, query):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError("检索词必须为 1–500 字。")
    terms = query_terms(query)
    if not terms:
        return []
    rows = []

    def add(kind, pk, title, text, location, url=""):
        if not text.strip():
            return
        rows.append({"type": kind, "id": pk, "title": title, "location": location,
                     "excerpt": excerpt(text, query, terms), "url": url,
                     "sha256": hashlib.sha256(text.encode()).hexdigest()})

    evidence = visible_evidence(user)
    # Materials currently have no space membership. A space-only scope must not broaden to them.
    if "space_ids" in scope or (scope and "material_ids" not in scope):
        evidence = evidence.none()
    elif "material_ids" in scope:
        evidence = evidence.filter(version__material_id__in=scope["material_ids"])
    for row in _matches(evidence, terms, ["text", "version__material__title"])[:6]:
        location = f"版本 {row.version.number}，" + (f"第 {row.page} 页" if row.page else f"第 {row.line_start}–{row.line_end} 行")
        if row.review_required and not row.reviewed_at:
            location += "，提取内容待人工核对"
        add("material", row.pk, row.version.material.title, row.text, location,
            f"/materials/{row.version.material_id}?version={row.version_id}#evidence-{row.pk}")
    documents = _scoped(DocumentVersion.objects.filter(is_current=True).select_related("document"), scope,
                        "document_ids", "document_id", "document__space_id")
    for row in _matches(documents, terms, ["markdown", "document__title"])[:4]:
        add("document", row.pk, row.document.title, row.markdown, f"文档版本 {row.version}，引用时正文摘录")
    papers = _scoped(Paper.objects.all(), scope, "paper_ids")
    for row in _matches(papers, terms, ["title", "abstract"])[:4]:
        add("paper", row.pk, row.title, row.abstract, "论文摘要，非全文；引用时快照")
    experiments = _scoped(accessible_experiments(user), scope, "experiment_ids")
    for row in _matches(experiments, terms, ["title", "objective", "protocol_markdown"])[:4]:
        add("experiment", row.pk, row.title, row.objective + "\n" + row.protocol_markdown,
            "实验目标与方案，引用时快照")
    if not scope or "note_ids" in scope:
        notes = PersonalEntry.objects.filter(owner=user, kind="note", enabled=True)
        if "note_ids" in scope:
            notes = notes.filter(pk__in=scope["note_ids"])
        for row in _matches(notes, terms, ["title", "body"])[:4]:
            add("personal_note", row.pk, row.title, row.body, "本人的研究记录，非发表论文；引用时快照")
    if not scope:
        for row in _matches(ResearchPublication.objects.all(), terms, ["title", "body"])[:20]:
            if publication_allowed(row):
                add("publication", row.pk, row.title, row.body, "成员明确发布的研究记录，非论文结论")
    rows.sort(key=lambda row: sum(term in (row["title"] + row["excerpt"]).casefold() for term in terms), reverse=True)
    return rows[:8]
