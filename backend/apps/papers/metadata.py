from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


INVALID_TITLES = {"untitled", "untitled paper", "unknown", "none", "null"}
DEFAULT_UPLOAD_TITLE = "Paper upload"
NOISY_TITLE_PATTERNS = [
    re.compile(r"^(?:published as|accepted at|under review|conference paper|proceedings of)\b", re.IGNORECASE),
    re.compile(r"\b(?:georgia institute|university|department|school|college|institute of technology)\b", re.IGNORECASE),
    re.compile(r"\b(?:@|\.edu\b|\.com\b|atlanta,\s*ga)\b", re.IGNORECASE),
]
ABSTRACT_PREFIX_RE = re.compile(r"^\s*(?:abstract|summary)\s*[:.\-]\s*", re.IGNORECASE)
NON_ABSTRACT_PATTERNS = [
    re.compile(r"^\s*(?:published as|accepted as|accepted at|conference paper|proceedings of)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:journal|volume|issue|pages?|doi|arxiv)\b\s*[:\-]?", re.IGNORECASE),
    re.compile(r"\b(?:google scholar|semantic scholar|researchgate|download pdf|bibtex|citation links?)\b", re.IGNORECASE),
    re.compile(r"\bthis page contains\b", re.IGNORECASE),
]
ABSTRACT_CONTENT_TERMS = {
    "propose",
    "proposes",
    "proposed",
    "present",
    "presents",
    "presented",
    "introduce",
    "introduces",
    "develop",
    "develops",
    "study",
    "studies",
    "investigate",
    "investigates",
    "demonstrate",
    "demonstrates",
    "show",
    "shows",
    "evaluate",
    "evaluates",
    "method",
    "model",
    "framework",
    "algorithm",
    "approach",
    "learning",
    "neural",
    "physics",
    "equation",
    "equations",
    "pde",
    "pdes",
    "benchmark",
    "benchmarks",
    "experiment",
    "experiments",
    "result",
    "results",
}


@dataclass(frozen=True)
class ExtractedPaperMetadata:
    title: str = ""
    authors: list[str] | None = None
    year: int | None = None
    doi: str = ""
    arxiv_id: str = ""
    abstract: str = ""
    source_url: str = ""
    text: str = ""


def extract_pdf_metadata(data: bytes, *, filename: str = "", provided_title: str | None = None) -> ExtractedPaperMetadata:
    reader = PdfReader(BytesIO(data), strict=False)
    metadata = reader.metadata or {}
    text = extract_text(reader)
    title = (
        normalize_paper_title(provided_title or "", from_filename=False)
        or normalize_paper_title(_metadata_value(metadata, "title", "/Title"), from_filename=False)
        or normalize_paper_title(title_from_first_page_text(text), from_filename=False)
        or DEFAULT_UPLOAD_TITLE
    )
    authors = split_authors(_metadata_value(metadata, "author", "/Author")) or extract_authors_from_text(text, title)
    abstract = clean_abstract(_metadata_value(metadata, "subject", "/Subject")) or extract_abstract_preview(text)
    year = extract_year(text, metadata)
    doi = extract_doi(f"{metadata} {text}")
    arxiv_id = extract_arxiv(f"{filename} {metadata} {text}")
    source_url = source_url_for(doi=doi, arxiv_id=arxiv_id)
    return ExtractedPaperMetadata(
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        arxiv_id=arxiv_id,
        abstract=abstract,
        source_url=source_url,
        text=text,
    )


def extract_text(reader: PdfReader, max_pages: int = 8, max_chars: int = 24000) -> str:
    parts = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
        if sum(len(part) for part in parts) >= max_chars:
            break
    return re.sub(r"\s+", " ", "\n".join(parts)).strip()[:max_chars]


def title_from_filename(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    stem = re.sub(r"-[0-9a-f]{12}$", "", stem, flags=re.IGNORECASE)
    return normalize_paper_title(stem, from_filename=True) or "Paper upload"


def title_from_first_page_text(text: str) -> str:
    if not text:
        return ""
    head = re.sub(r"\s+", " ", text[:2500]).strip()
    if not head:
        return ""
    abstract_match = re.search(r"\babstract\b", head, flags=re.IGNORECASE)
    if abstract_match:
        head = head[: abstract_match.start()].strip()
    head = _clean_title_candidate_region(head)
    sentences = re.split(r"(?<=[.!?])\s+", head)
    candidates = [head, *sentences[:4]]
    for sentence in candidates:
        title = normalize_paper_title(sentence, from_filename=False)
        if title:
            return title
    return ""


def _clean_title_candidate_region(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    text = re.sub(
        r"^(?:published as|accepted as|accepted at|under review|conference paper|proceedings of)\b.*?\b(?:20\d{2}|19\d{2})\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    affiliation_match = re.search(
        r"\b(?:[A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z]+)\s+(?:Georgia Institute|Carnegie Mellon|University|Department|School|College|Institute of Technology)\b",
        text,
    )
    if affiliation_match:
        text = text[: affiliation_match.start()].strip()
    email_match = re.search(r"\b\S+@\S+\b", text)
    if email_match:
        text = text[: email_match.start()].strip()
    return text


def normalize_paper_title(value: object, *, from_filename: bool) -> str:
    title = str(value or "").strip()
    if not title:
        return ""
    title = re.sub(r"\.pdf$", "", title, flags=re.IGNORECASE).strip()
    title = title.replace("_", " ")
    if from_filename:
        title = re.sub(r"[_\-]+", " ", title)
        title = re.sub(r"\b(?:arxiv|download|downloads|paper|final|submitted|main)\b", " ", title, flags=re.IGNORECASE)
        title = re.sub(r"(?<=\d)\.(?=\d)", " ", title)
    else:
        title = re.sub(r"^(?:arxiv|download(?:ed)?(?: paper)?|paper download)\s*[:\-]?\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" -_.,;:[](){}")
    if not title:
        return ""
    if from_filename and not re.search(r"[A-Za-z\u4e00-\u9fff]", title):
        title = f"Paper {title}"
    if title.lower() in INVALID_TITLES:
        return ""
    if title.isdigit() or len(title) < 8:
        return ""
    if len(title) > 220:
        title = title[:220].rsplit(" ", 1)[0].strip() or title[:220].strip()
    if not from_filename and _looks_like_noisy_pdf_title(title):
        return ""
    return title


def _looks_like_noisy_pdf_title(title: str) -> bool:
    lowered = title.lower()
    if any(pattern.search(title) for pattern in NOISY_TITLE_PATTERNS):
        return True
    if len(title) > 150 and sum(token in lowered for token in ("author", "abstract", "paper", "conference", "work")) >= 2:
        return True
    if len(re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", title)) >= 2 and len(title) > 120:
        return True
    return False


def split_authors(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"\s*(?:,|;|\band\b|&)\s*", value)
    return [part.strip() for part in parts if len(part.strip()) >= 2][:20]


def extract_authors_from_text(text: str, title: str) -> list[str]:
    if not text:
        return []
    head = text[:3000]
    abstract_match = re.search(r"\bABSTRACT\b", head, flags=re.IGNORECASE)
    if abstract_match:
        head = head[: abstract_match.start()]
    title_words = [word for word in re.split(r"\W+", title.lower()) if len(word) >= 4]
    if title_words:
        lowered_head = head.lower()
        ends = []
        for word in title_words:
            position = lowered_head.find(word)
            if position >= 0:
                ends.append(position + len(word))
        if ends:
            head = head[max(ends) :]
    affiliation_pattern = re.compile(
        r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\s+"
        r"(?:Georgia|Carnegie|University|Institute|Department|School|College)\b"
    )
    affiliation_authors = []
    for match in affiliation_pattern.finditer(head):
        candidate = clean_author_candidate(match.group(1))
        if candidate and candidate not in affiliation_authors:
            affiliation_authors.append(candidate)
    return affiliation_authors[:20]


def clean_author_candidate(value: str) -> str:
    parts = value.split()
    while parts and re.fullmatch(r"[A-Z]{2}", parts[0]):
        parts.pop(0)
    while parts and parts[-1] in {"Georgia", "Carnegie", "University", "Institute", "Department", "School", "College"}:
        parts.pop()
    return " ".join(parts).strip()


def extract_year(text: str, metadata: object) -> int | None:
    haystack = f"{metadata} {text[:3000]}"
    match = re.search(r"\b(19[8-9]\d|20[0-4]\d)\b", haystack)
    return int(match.group(1)) if match else None


def extract_doi(text: str) -> str:
    match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", text, re.IGNORECASE)
    return match.group(0).rstrip(".,;)") if match else ""


def extract_arxiv(text: str) -> str:
    match = re.search(r"(?:arXiv[:_\s-]*)?(\d{4}\.\d{4,5})(?:v\d+)?", text, re.IGNORECASE)
    return match.group(1) if match else ""


def clean_abstract(value: object, *, automatic: bool = True) -> str:
    abstract = re.sub(r"\s+", " ", str(value or "")).strip()
    if not abstract or abstract.lower() in INVALID_TITLES:
        return ""
    abstract = ABSTRACT_PREFIX_RE.sub("", abstract).strip()
    if automatic and not is_valid_automatic_abstract(abstract):
        return ""
    return abstract[:2000]


def is_valid_automatic_abstract(value: object) -> bool:
    abstract = re.sub(r"\s+", " ", str(value or "")).strip()
    if not abstract or abstract.lower() in INVALID_TITLES:
        return False
    if len(abstract) < 40:
        return False
    lowered = abstract.lower()
    if any(pattern.search(abstract) for pattern in NON_ABSTRACT_PATTERNS):
        return False
    if _looks_like_citation_record(abstract):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z-]+", lowered)
    if len(words) < 7:
        return False
    return any(term in words for term in ABSTRACT_CONTENT_TERMS)


def _looks_like_citation_record(value: str) -> bool:
    lowered = value.lower()
    citation_markers = sum(
        marker in lowered
        for marker in (
            "volume ",
            " issue ",
            "article ",
            "doi:",
            "issn",
            "pp.",
            "pages ",
            "published ",
        )
    )
    content_markers = sum(term in re.findall(r"[A-Za-z][A-Za-z-]+", lowered) for term in ABSTRACT_CONTENT_TERMS)
    if citation_markers >= 2 and content_markers <= 1:
        return True
    if re.search(r"\b(?:volume|vol\.)\s+\d+", lowered) and re.search(r"\b10\.\d{4,9}/", lowered):
        return True
    return False


def extract_abstract_preview(text: str) -> str:
    match = re.search(r"\babstract\b[:.\s-]*(.{80,2000})", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    abstract = re.split(r"\b(?:keywords|introduction|1\s+introduction)\b", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
    return clean_abstract(abstract)


def source_url_for(*, doi: str = "", arxiv_id: str = "") -> str:
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    if doi:
        return f"https://doi.org/{doi}"
    return ""


def _metadata_value(metadata: object, attr: str, key: str) -> str:
    value = getattr(metadata, attr, "") or ""
    if not value and hasattr(metadata, "get"):
        value = metadata.get(key, "")
    return str(value or "").strip()
