from __future__ import annotations

from django.db import transaction

from apps.library.keywords import canonical_keyword_names, get_or_create_canonical_keyword
from apps.papers.light_processing import enqueue_light_processing
from apps.papers.metadata import DEFAULT_UPLOAD_TITLE, clean_abstract
from apps.papers.metadata_completion import MetadataSuggestionUnavailable, suggest_paper_metadata
from apps.papers.models import Paper
from apps.tasks.models import TaskRecord
from apps.tasks.sanitization import sanitize_task_error


POST_UPLOAD_TASK_TYPE = "paper_upload_postprocess"


def enqueue_upload_postprocess(paper: Paper) -> TaskRecord:
    with transaction.atomic():
        locked_paper = Paper.objects.select_for_update().get(pk=paper.pk)
        active_task = (
            TaskRecord.objects.filter(
                object_type="paper",
                object_id=locked_paper.id,
                task_type=POST_UPLOAD_TASK_TYPE,
                status__in=[TaskRecord.Status.PENDING, TaskRecord.Status.RUNNING],
            )
            .order_by("-updated_at", "-id")
            .first()
        )
        if active_task:
            return active_task

        task = TaskRecord.objects.create(
            task_type=POST_UPLOAD_TASK_TYPE,
            status=TaskRecord.Status.PENDING,
            progress=0,
            stage="queued",
            object_type="paper",
            object_id=locked_paper.id,
            result={"paper_id": locked_paper.id},
        )

    from apps.papers.tasks import run_paper_upload_postprocess_task

    try:
        run_paper_upload_postprocess_task.apply_async(args=[task.object_id, task.id], queue="ai_q")
    except Exception as exc:
        task.status = TaskRecord.Status.FAILED
        task.progress = 100
        task.stage = "publish_failed"
        task.error = "Unable to publish upload postprocess task."
        task.result = {**_dict_result(task.result), "error": sanitize_task_error(exc)}
        task.save(update_fields=["status", "progress", "stage", "error", "result", "updated_at"])
    return task


def run_upload_postprocess_with_task(paper: Paper, *, task: TaskRecord) -> TaskRecord:
    task.status = TaskRecord.Status.RUNNING
    task.progress = 10
    task.stage = "metadata_completion"
    task.save(update_fields=["status", "progress", "stage", "updated_at"])

    result: dict[str, object] = {"paper_id": paper.id, "metadata_applied": False}
    try:
        suggestion_payload = suggest_paper_metadata(paper)
        suggestions = suggestion_payload.get("suggestions", {})
        if isinstance(suggestions, dict):
            suggestions = _merge_candidate_fallbacks(suggestions, suggestion_payload.get("candidates"))
            applied_fields = apply_metadata_suggestions(paper, suggestions)
            rejected_reason = _metadata_rejection_reason(paper, suggestions) if not applied_fields else ""
            result.update(
                {
                    "metadata_applied": bool(applied_fields),
                    "applied_fields": applied_fields,
                    "metadata_provider": suggestion_payload.get("provider", ""),
                    "metadata_model": suggestion_payload.get("model", ""),
                    "metadata_confidence": suggestions.get("confidence", 0.0),
                }
            )
            if rejected_reason:
                result["metadata_rejected"] = rejected_reason
    except MetadataSuggestionUnavailable as exc:
        result["metadata_error"] = sanitize_task_error(exc)

    task.progress = 70
    task.stage = "queue_ai_light_profile"
    task.result = result
    task.save(update_fields=["progress", "stage", "result", "updated_at"])

    paper.refresh_from_db()
    light_task = enqueue_light_processing(paper, use_ai=True)
    task.status = TaskRecord.Status.SUCCESS
    task.progress = 100
    task.stage = "postprocess_ready"
    task.result = {**result, "light_task_id": light_task.id}
    task.save(update_fields=["status", "progress", "stage", "result", "updated_at"])
    return task


def apply_metadata_suggestions(paper: Paper, suggestions: dict[str, object]) -> list[str]:
    applied: list[str] = []
    with transaction.atomic():
        locked_paper = Paper.objects.select_for_update().get(pk=paper.pk)
        confidence = _clean_confidence(suggestions.get("confidence"))
        identity_match = _matches_existing_identity(locked_paper, suggestions)
        has_existing_identity = bool(locked_paper.arxiv_id or locked_paper.doi or locked_paper.source_url)
        trusted_metadata = confidence >= 0.65 or identity_match
        provisional_title_allowed = (
            not has_existing_identity
            and confidence >= 0.3
            and bool(_clean_text(suggestions.get("arxiv_id")) or _clean_text(suggestions.get("doi")) or _clean_text(suggestions.get("source_url")))
        )
        title = _clean_text(suggestions.get("title"))[:500]
        if title and _needs_title_completion(locked_paper.title) and (trusted_metadata or provisional_title_allowed):
            locked_paper.title = title
            applied.append("title")

        authors = suggestions.get("authors")
        if isinstance(authors, list) and authors and not locked_paper.authors and trusted_metadata:
            locked_paper.authors = [
                str(item).strip() for item in authors if _looks_like_author_name(str(item).strip())
            ]
            if locked_paper.authors:
                applied.append("authors")

        year = _clean_year(suggestions.get("year"))
        if year and not locked_paper.year and trusted_metadata:
            locked_paper.year = year
            applied.append("year")

        for field, limit in (
            ("venue", 180),
            ("doi", 160),
            ("arxiv_id", 80),
            ("source_url", 500),
        ):
            value = _clean_text(suggestions.get(field))[:limit]
            if value and not getattr(locked_paper, field) and (trusted_metadata or field in {"arxiv_id", "doi", "source_url"} and provisional_title_allowed):
                setattr(locked_paper, field, value)
                applied.append(field)

        abstract = clean_abstract(suggestions.get("abstract"))
        if abstract and not locked_paper.abstract and trusted_metadata:
            locked_paper.abstract = abstract
            applied.append("abstract")

        if applied:
            locked_paper.save()

        keywords = suggestions.get("keywords")
        if isinstance(keywords, list) and (trusted_metadata or provisional_title_allowed):
            existing_names = list(locked_paper.keywords.values_list("name", flat=True))
            names = canonical_keyword_names([*existing_names, *[str(item).strip() for item in keywords if str(item).strip()]])[:12]
            if names:
                keyword_objects = [get_or_create_canonical_keyword(name) for name in names]
                locked_paper.keywords.set(keyword_objects)
                applied.append("keywords")
    return applied


def _merge_candidate_fallbacks(suggestions: dict[str, object], candidates: object) -> dict[str, object]:
    if not isinstance(candidates, list):
        return suggestions
    merged = dict(suggestions)
    first_candidate = next((item for item in candidates if isinstance(item, dict)), None)
    if not first_candidate:
        return merged
    for key in ("title", "arxiv_id", "source_url", "doi", "venue", "abstract", "year"):
        if not _clean_text(merged.get(key)) and _clean_text(first_candidate.get(key)):
            merged[key] = first_candidate.get(key)
    if not merged.get("keywords") and isinstance(first_candidate.get("keywords"), list):
        merged["keywords"] = first_candidate.get("keywords")
    return merged


def _needs_title_completion(title: str) -> bool:
    normalized = str(title or "").strip().lower()
    return normalized in {"", DEFAULT_UPLOAD_TITLE.lower(), "untitled paper"} or normalized.startswith("paper upload")


def _metadata_rejection_reason(paper: Paper, suggestions: dict[str, object]) -> str:
    if _clean_confidence(suggestions.get("confidence")) >= 0.65:
        return ""
    if _matches_existing_identity(paper, suggestions):
        return ""
    if not any(_clean_text(suggestions.get(key)) for key in ("title", "authors", "year", "venue", "abstract", "keywords")):
        return ""
    return "low_confidence_or_identity_mismatch"


def _matches_existing_identity(paper: Paper, suggestions: dict[str, object]) -> bool:
    suggested_arxiv = _clean_text(suggestions.get("arxiv_id")).lower().removeprefix("arxiv:")
    existing_arxiv = _clean_text(paper.arxiv_id).lower().removeprefix("arxiv:")
    if existing_arxiv and suggested_arxiv:
        return existing_arxiv == suggested_arxiv
    suggested_doi = _clean_text(suggestions.get("doi")).lower()
    existing_doi = _clean_text(paper.doi).lower()
    if existing_doi and suggested_doi:
        return existing_doi == suggested_doi
    suggested_url = _clean_text(suggestions.get("source_url")).lower()
    existing_url = _clean_text(paper.source_url).lower()
    if existing_url and suggested_url:
        return existing_url.rstrip("/") == suggested_url.rstrip("/")
    if existing_arxiv and suggested_url:
        return existing_arxiv in suggested_url
    if existing_doi and suggested_url:
        return existing_doi in suggested_url
    return False


def _clean_confidence(value: object) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(parsed, 1.0))


def _looks_like_author_name(value: str) -> bool:
    if not value or len(value) > 120:
        return False
    lowered = value.lower()
    blocked = {
        "new york",
        "atlanta",
        "pittsburgh",
        "united states",
        "google scholar",
        "researchgate",
        "arxiv",
    }
    if lowered in blocked:
        return False
    if any(token in lowered for token in ("university", "institute", "department", "laboratory", "http", "@")):
        return False
    parts = [part for part in value.replace(".", " ").replace("-", " ").split() if part]
    return len(parts) >= 2 and any(part[:1].isupper() for part in parts)


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_year(value: object) -> int | None:
    try:
        year = int(value) if value else None
    except (TypeError, ValueError):
        return None
    if year is None or year < 1800 or year > 2200:
        return None
    return year


def _dict_result(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
