from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.papers.metadata import normalize_paper_title, split_authors
from apps.papers.metadata_completion import _extract_arxiv_id, _extract_doi, _extract_year


@dataclass
class ReferenceCandidate:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    source_url: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    raw: str = ""
    confidence: float = 0.55
    source: str = "reference_import"

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "source_url": self.source_url,
            "abstract": self.abstract,
            "keywords": self.keywords,
            "raw": self.raw,
            "confidence": self.confidence,
            "source": self.source,
        }


def parse_reference_candidates(content: str, *, limit: int = 20) -> list[dict[str, object]]:
    text = str(content or "").strip()
    if not text:
        return []
    if re.search(r"^TY\s+-\s+", text, re.MULTILINE):
        candidates = _parse_ris(text)
    elif re.search(r"@\w+\s*\{", text):
        candidates = _parse_bibtex(text)
    else:
        candidates = _parse_plain_references(text)
    return [candidate.as_dict() for candidate in candidates[:limit] if candidate.title]


def _parse_ris(text: str) -> list[ReferenceCandidate]:
    records = re.split(r"(?m)^ER\s+-.*$", text)
    candidates: list[ReferenceCandidate] = []
    for record in records:
        fields: dict[str, list[str]] = {}
        for line in record.splitlines():
            match = re.match(r"^([A-Z0-9]{2})\s+-\s*(.*)$", line.strip())
            if match:
                fields.setdefault(match.group(1), []).append(match.group(2).strip())
        title = _first(fields, "TI", "T1", "CT")
        if not title:
            continue
        candidate = ReferenceCandidate(
            title=_clean_title(title),
            authors=[author for key in ("AU", "A1") for author in fields.get(key, []) if author],
            year=_year_from_values(fields.get("PY", []) + fields.get("Y1", [])),
            venue=_first(fields, "JO", "JF", "T2", "BT", "PB"),
            doi=_first(fields, "DO") or _extract_doi(record),
            source_url=_first(fields, "UR"),
            abstract=_first(fields, "AB", "N2"),
            keywords=[item for item in fields.get("KW", []) if item],
            raw=record.strip(),
            confidence=0.82,
            source="ris_import",
        )
        candidate.arxiv_id = _extract_arxiv_id(f"{candidate.source_url} {candidate.doi} {record}")
        candidates.append(candidate)
    return candidates


def _parse_bibtex(text: str) -> list[ReferenceCandidate]:
    candidates: list[ReferenceCandidate] = []
    for entry in _bibtex_entries(text):
        fields = _bibtex_fields(entry)
        title = fields.get("title", "")
        if not title:
            continue
        venue = fields.get("journal") or fields.get("booktitle") or fields.get("publisher") or fields.get("school") or ""
        keywords = _split_keywords(fields.get("keywords", ""))
        candidate = ReferenceCandidate(
            title=_clean_title(title),
            authors=split_authors(fields.get("author", "").replace(" and ", "; ")),
            year=_year_from_values([fields.get("year", "")]),
            venue=venue,
            doi=fields.get("doi", "") or _extract_doi(entry),
            source_url=fields.get("url", ""),
            abstract=fields.get("abstract", ""),
            keywords=keywords,
            raw=entry.strip(),
            confidence=0.8,
            source="bibtex_import",
        )
        candidate.arxiv_id = fields.get("eprint", "") or _extract_arxiv_id(f"{candidate.source_url} {candidate.doi} {entry}")
        candidates.append(candidate)
    return candidates


def _parse_plain_references(text: str) -> list[ReferenceCandidate]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n|(?m)^\s*\[\d+\]\s+", text) if chunk.strip()]
    candidates: list[ReferenceCandidate] = []
    for chunk in chunks:
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        raw = " ".join(lines)
        title = _guess_plain_title(raw)
        if not title:
            continue
        candidates.append(
            ReferenceCandidate(
                title=_clean_title(title),
                year=_extract_year(raw),
                doi=_extract_doi(raw),
                arxiv_id=_extract_arxiv_id(raw),
                source_url=_first_url(raw),
                raw=chunk,
                confidence=0.45,
                source="plain_reference_import",
            )
        )
    return candidates


def _bibtex_entries(text: str) -> list[str]:
    entries: list[str] = []
    index = 0
    while True:
        start = text.find("@", index)
        if start < 0:
            break
        brace = text.find("{", start)
        if brace < 0:
            break
        depth = 0
        end = brace
        while end < len(text):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
            end += 1
        entries.append(text[start:end])
        index = end
    return entries


def _bibtex_fields(entry: str) -> dict[str, str]:
    body_start = entry.find("{")
    body = entry[body_start + 1 : -1] if body_start >= 0 else entry
    body = body.split(",", 1)[1] if "," in body else body
    fields: dict[str, str] = {}
    pattern = re.compile(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)", re.DOTALL)
    for match in pattern.finditer(body):
        key = match.group(1).strip().lower()
        value = match.group(2).strip().strip(",")
        fields[key] = _strip_bibtex_value(value)
    return fields


def _strip_bibtex_value(value: str) -> str:
    value = value.strip()
    if (value.startswith("{") and value.endswith("}")) or (value.startswith('"') and value.endswith('"')):
        value = value[1:-1]
    return re.sub(r"\s+", " ", value).strip()


def _first(fields: dict[str, list[str]], *keys: str) -> str:
    for key in keys:
        values = fields.get(key, [])
        if values:
            return values[0].strip()
    return ""


def _year_from_values(values: list[str]) -> int | None:
    for value in values:
        year = _extract_year(value)
        if year:
            return year
    return None


def _split_keywords(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;]\s*", value or "") if item.strip()]


def _first_url(value: str) -> str:
    match = re.search(r"https?://\S+", value or "")
    return match.group(0).rstrip(").,;") if match else ""


def _guess_plain_title(value: str) -> str:
    quoted = re.search(r"[\"“](.+?)[\"”]", value)
    if quoted:
        return quoted.group(1)
    parts = [part.strip() for part in re.split(r"\.\s+", value, maxsplit=3) if part.strip()]
    if len(parts) >= 2:
        return parts[1]
    return parts[0] if parts else ""


def _clean_title(value: str) -> str:
    return normalize_paper_title(value, from_filename=False) or re.sub(r"\s+", " ", value).strip()[:500]
