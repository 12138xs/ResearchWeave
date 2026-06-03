from __future__ import annotations

from pathlib import Path

from django.utils.text import slugify

from apps.papers.models import Paper
from apps.storage.provider import get_storage_provider


def resolve_paper_pdf_path(paper: Paper) -> Path | None:
    if not paper.source_pdf_path:
        return None
    try:
        path = get_storage_provider().resolve(paper.source_pdf_path)
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def paper_download_filename(paper: Paper) -> str:
    stem = slugify(paper.title, allow_unicode=True)[:180] or paper.slug or str(paper.pk)
    if paper.year and str(paper.year) not in stem:
        stem = f"{stem}-{paper.year}"
    return f"{stem}.pdf"
