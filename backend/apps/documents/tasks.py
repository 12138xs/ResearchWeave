from __future__ import annotations

from celery import shared_task
from django.utils.text import Truncator

from apps.documents.importing import generate_candidate_from_text
from apps.documents.models import DocumentImportBatch, DocumentImportCandidate, DocumentSource


@shared_task(queue="ai_q")
def generate_document_import_candidates(batch_id: int) -> dict[str, int]:
    batch = DocumentImportBatch.objects.prefetch_related("sources").get(pk=batch_id)
    batch.status = DocumentImportBatch.Status.PROCESSING
    batch.error_message = ""
    batch.save(update_fields=["status", "error_message", "updated_at"])

    created = 0
    try:
        for source in batch.sources.all():
            source_text = source.raw_excerpt or source.title or source.url
            if batch.options_json.get("generation_mode") == "fallback_only":
                title = source.title or source.url or "未命名资料"
                summary = Truncator(source_text).chars(180)
                markdown = _fallback_markdown(source=source, source_text=source_text, reason="批次设置为目录级保底导入")
                keywords = []
                quality_notes = "按批次设置生成保底草稿，供人工审核后再决定是否深度整理。"
                confidence = 0.2
            else:
                try:
                    draft = generate_candidate_from_text(
                        source_title=source.title or source.url or "未命名资料",
                        source_text=source_text,
                        source_attribution=source.attribution or source.url or source.source_type,
                    )
                    title = draft.title
                    summary = draft.summary
                    markdown = draft.markdown
                    keywords = draft.keywords
                    quality_notes = draft.quality_notes
                    confidence = draft.confidence
                except ValueError as exc:
                    title = source.title or source.url or "未命名资料"
                    summary = Truncator(source_text).chars(180)
                    markdown = _fallback_markdown(source=source, source_text=source_text, reason=str(exc))
                    keywords = []
                    quality_notes = f"AI 生成失败，已生成保底草稿供人工审核：{exc}"
                    confidence = 0.2

            DocumentImportCandidate.objects.create(
                batch=batch,
                source=source,
                target_space=batch.target_space,
                proposed_title=title,
                proposed_summary=summary,
                proposed_markdown=markdown,
                proposed_keywords=keywords,
                quality_notes=quality_notes,
                confidence=confidence,
                status=DocumentImportCandidate.Status.NEEDS_REVIEW,
            )
            created += 1
    except Exception as exc:
        batch.status = DocumentImportBatch.Status.FAILED
        batch.error_message = (
            f"Candidate generation failed after {created} source(s): {exc}"
        )
        batch.save(update_fields=["status", "error_message", "updated_at"])
        raise

    batch.status = DocumentImportBatch.Status.NEEDS_REVIEW
    batch.save(update_fields=["status", "updated_at"])
    return {"created": created}


def _fallback_markdown(*, source: DocumentSource, source_text: str, reason: str) -> str:
    title = source.title or source.url or "未命名资料"
    source_label = source.attribution or source.url or source.source_type
    return (
        f"# {title}\n\n"
        "## 来源\n\n"
        f"- 来源：{source_label}\n"
        f"- URL：{source.url or '无'}\n\n"
        "## 待整理内容\n\n"
        f"{source_text}\n\n"
        "## 人工审核提示\n\n"
        f"AI 草稿生成失败，原因：{reason}\n\n"
        "请人工检查来源、授权、事实准确性和适合归入的知识体系，再决定是否采纳。"
    )
