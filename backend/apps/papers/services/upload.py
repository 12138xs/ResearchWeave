from __future__ import annotations

from uuid import uuid4

from django.utils.text import slugify

from apps.papers.metadata import (
    DEFAULT_UPLOAD_TITLE,
    ExtractedPaperMetadata,
    extract_pdf_metadata,
    normalize_paper_title,
    title_from_filename,
    title_from_first_page_text,
)
from apps.papers.models import Paper
from apps.papers.post_upload import enqueue_upload_postprocess
from apps.storage.provider import get_storage_provider
from apps.tasks.models import TaskRecord


def create_uploaded_paper(upload, validated_data: dict) -> tuple[Paper, str, TaskRecord]:
    metadata = metadata_from_upload(upload, validated_data.get("title"))
    storage_key = save_quarantine_pdf(upload)
    try:
        paper = Paper.objects.create(
            title=metadata.title,
            authors=metadata.authors or [],
            year=validated_data.get("year") or metadata.year,
            venue=validated_data.get("venue", ""),
            area=validated_data.get("area", ""),
            abstract=metadata.abstract,
            doi=metadata.doi[:160],
            arxiv_id=metadata.arxiv_id[:80],
            source_url=metadata.source_url[:500],
            source_pdf_path=storage_key,
            status=Paper.Status.UPLOADED,
        )
    except Exception:
        get_storage_provider().resolve(storage_key).unlink(missing_ok=True)
        raise
    return paper, storage_key, enqueue_upload_postprocess(paper)


def title_from_upload(upload, provided_title: str | None = None) -> str:
    return metadata_from_upload(upload, provided_title).title


def metadata_from_upload(upload, provided_title: str | None = None):
    provided = normalize_paper_title(provided_title or "", from_filename=False)
    data = upload.read()
    upload.seek(0)
    try:
        return extract_pdf_metadata(data, filename=upload.name, provided_title=provided)
    except Exception:
        return ExtractedPaperMetadata(title=provided or DEFAULT_UPLOAD_TITLE)


def safe_pdf_name(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    safe_stem = slugify(stem, allow_unicode=True) or "paper"
    return f"{safe_stem[:80]}-{uuid4().hex[:12]}.pdf"


def save_quarantine_pdf(upload) -> str:
    provider = get_storage_provider()
    provider.ensure_runtime_dirs()
    storage_key = f"quarantine/uploads/{safe_pdf_name(upload.name)}"
    target = provider.resolve(storage_key)
    with target.open("wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)
    return storage_key


__all__ = [
    "create_uploaded_paper",
    "metadata_from_upload",
    "normalize_paper_title",
    "save_quarantine_pdf",
    "title_from_filename",
    "title_from_first_page_text",
    "title_from_upload",
]
