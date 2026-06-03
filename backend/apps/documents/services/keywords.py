from __future__ import annotations

from apps.documents.models import Document
from apps.library.keywords import get_or_create_canonical_keyword


def set_document_keywords(document: Document, values: object) -> None:
    if not isinstance(values, list):
        values = []
    keyword_objects = [
        get_or_create_canonical_keyword(str(value).strip())
        for value in values
        if str(value).strip()
    ]
    document.keywords.set(keyword_objects)
