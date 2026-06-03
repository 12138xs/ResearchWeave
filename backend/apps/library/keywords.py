from __future__ import annotations

import re

from apps.library.models import Keyword


CANONICAL_KEYWORD_ALIASES: dict[str, list[str]] = {
    "PINN": [
        "Physics-Informed Neural Network",
        "Physics-Informed Neural Networks",
        "PINNs",
    ],
    "PDE": [
        "PDEs",
        "Partial Differential Equation",
        "Partial Differential Equations",
    ],
    "Graph Neural Networks": [
        "Graph Neural Network",
        "GNN",
        "GNNs",
    ],
    "Finite Volume Methods": [
        "Finite Volume Method",
        "FVM",
    ],
    "Conservation Laws": [
        "Conservation Law",
    ],
    "Wavelet Activation": [
        "Wavelet Activation Function",
    ],
}


def normalize_keyword_text(value: str) -> str:
    cleaned = clean_keyword_value(value).lower()
    cleaned = re.sub(r"[-_/]+", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9+ ]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned)


def canonical_keyword_name(value: str) -> str:
    cleaned = clean_keyword_value(value)
    if not is_english_keyword(cleaned):
        return ""
    normalized = normalize_keyword_text(cleaned)
    for canonical, aliases in CANONICAL_KEYWORD_ALIASES.items():
        names = [canonical, *aliases]
        if normalized in {normalize_keyword_text(name) for name in names}:
            return canonical
    return cleaned


def clean_keyword_value(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[-*+\d.)\s]+", "", text)
    text = text.strip("`*_ \t\r\n\"'：:;；,，.。")
    text = re.sub(r"\s+", " ", text)
    return text


def is_english_keyword(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.search(r"[\u3400-\u9fff]", text):
        return False
    return bool(re.search(r"[A-Za-z]", text))


def canonical_keyword_names(values: list[str]) -> list[str]:
    seen: set[str] = set()
    canonical_values: list[str] = []
    for value in values:
        canonical = canonical_keyword_name(value)
        if not canonical:
            continue
        key = normalize_keyword_text(canonical)
        if canonical and key not in seen:
            seen.add(key)
            canonical_values.append(canonical)
    return canonical_values


def keyword_query_names(value: str) -> list[str]:
    canonical = canonical_keyword_name(value)
    if not canonical:
        return []
    names = [canonical, *CANONICAL_KEYWORD_ALIASES.get(canonical, [])]
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = normalize_keyword_text(name)
        if key not in seen:
            seen.add(key)
            unique.append(name)
    return unique


def get_or_create_canonical_keyword(value: str) -> Keyword:
    canonical = canonical_keyword_name(value)
    if not canonical:
        raise ValueError("Keyword must contain an English term.")
    normalized = normalize_keyword_text(canonical)
    existing = Keyword.objects.filter(normalized_name=normalized).first() or Keyword.objects.filter(name__iexact=canonical).first()
    if existing:
        if existing.normalized_name != normalized:
            existing.normalized_name = normalized
            existing.save(update_fields=["normalized_name", "updated_at"])
        return existing
    return Keyword.objects.create(name=canonical, normalized_name=normalized)


def merge_known_keyword_aliases(dry_run: bool = False) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for canonical, aliases in CANONICAL_KEYWORD_ALIASES.items():
        canonical_obj = get_or_create_canonical_keyword(canonical)
        for alias in aliases:
            alias_normalized = normalize_keyword_text(alias)
            alias_obj = (
                Keyword.objects.filter(normalized_name=alias_normalized).first()
                or Keyword.objects.filter(name__iexact=alias).first()
            )
            if not alias_obj or alias_obj.pk == canonical_obj.pk:
                continue
            paper_ids = list(alias_obj.papers.values_list("id", flat=True))
            document_ids = list(alias_obj.documents.values_list("id", flat=True))
            changes.append(
                {
                    "alias": alias_obj.name,
                    "canonical": canonical_obj.name,
                    "papers": paper_ids,
                    "documents": document_ids,
                }
            )
            if dry_run:
                continue
            for paper in alias_obj.papers.all():
                paper.keywords.add(canonical_obj)
            for document in alias_obj.documents.all():
                document.keywords.add(canonical_obj)
            alias_obj.delete()
    return changes


def prune_non_english_keywords(dry_run: bool = False) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for keyword in Keyword.objects.all().order_by("id"):
        if is_english_keyword(keyword.name):
            continue
        paper_ids = list(keyword.papers.values_list("id", flat=True))
        document_ids = list(keyword.documents.values_list("id", flat=True))
        changes.append(
            {
                "keyword": keyword.name,
                "papers": paper_ids,
                "documents": document_ids,
            }
        )
        if not dry_run:
            keyword.delete()
    return changes
