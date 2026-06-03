from __future__ import annotations

import json
import re
from urllib import parse, request

from django.conf import settings

from apps.ai.minimax import MiniMaxAPIError, MiniMaxConfigError, call_minimax_chat
from apps.library.keywords import canonical_keyword_names
from apps.papers.metadata import DEFAULT_UPLOAD_TITLE, clean_abstract, normalize_paper_title, split_authors
from apps.papers.models import Paper


class MetadataSuggestionUnavailable(RuntimeError):
    pass


SUGGESTION_FIELDS = {
    "title": "",
    "authors": [],
    "year": None,
    "venue": "",
    "doi": "",
    "arxiv_id": "",
    "source_url": "",
    "abstract": "",
    "keywords": [],
    "confidence": 0.0,
    "notes": "",
}


def suggest_paper_metadata(paper: Paper) -> dict[str, object]:
    evidence = run_metadata_web_search(paper)
    messages = _build_metadata_messages(paper, evidence)
    try:
        response = call_minimax_chat(messages)
    except (MiniMaxConfigError, MiniMaxAPIError) as exc:
        raise MetadataSuggestionUnavailable(str(exc)) from exc
    suggestions = _normalize_suggestions(_parse_json_object(response.content))
    return {
        "provider": "web_search+llm",
        "applied": False,
        "model": response.model,
        "usage": response.usage,
        "suggestions": suggestions,
        "evidence": evidence,
        "candidates": _candidate_papers_from_evidence(evidence, suggestions),
    }


def run_metadata_web_search(paper: Paper) -> list[dict[str, str]]:
    provider = str(getattr(settings, "WEB_SEARCH_PROVIDER", "disabled")).strip().lower()
    if provider in {"", "disabled", "none"}:
        raise MetadataSuggestionUnavailable("Web search metadata completion is not configured.")
    endpoint = str(getattr(settings, "WEB_SEARCH_ENDPOINT", "")).strip()
    api_key = str(getattr(settings, "WEB_SEARCH_API_KEY", "")).strip()
    if not endpoint:
        raise MetadataSuggestionUnavailable("WEB_SEARCH_ENDPOINT is not configured.")
    query = _search_query(paper)
    if provider == "searxng":
        params = {"q": query, "format": "json", "language": "en", "categories": "science,general"}
    else:
        params = {"q": query, "limit": 5}
    url = f"{endpoint}?{parse.urlencode(params)}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=int(getattr(settings, "WEB_SEARCH_TIMEOUT_SECONDS", 12))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MetadataSuggestionUnavailable(f"Web search request failed: {exc}") from exc
    return _normalize_search_results(payload)


def _search_query(paper: Paper) -> str:
    title = _searchable_title(paper.title)
    abstract_hint = _abstract_hint(paper.abstract)
    parts = [
        f"arXiv:{paper.arxiv_id}" if paper.arxiv_id else "",
        f"DOI:{paper.doi}" if paper.doi else "",
        paper.source_url,
        f'"{title}"' if title else "",
        " ".join(str(author) for author in (paper.authors or [])[:3]),
        str(paper.year or ""),
        paper.venue,
        abstract_hint,
    ]
    return " ".join(part for part in parts if part).strip()


def _searchable_title(title: str) -> str:
    normalized = str(title or "").strip()
    if not normalized:
        return ""
    lowered = normalized.lower()
    if lowered in {DEFAULT_UPLOAD_TITLE.lower(), "untitled paper"} or lowered.startswith("paper upload"):
        return ""
    return normalized


def _abstract_hint(abstract: str) -> str:
    text = re.sub(r"\s+", " ", str(abstract or "")).strip()
    if not text:
        return ""
    sentence = re.split(r"(?<=[.!?。！？])\s+", text, maxsplit=1)[0]
    return sentence[:180]


def _normalize_search_results(payload: object) -> list[dict[str, str]]:
    if isinstance(payload, dict):
        raw_results = payload.get("results") or payload.get("items") or []
    elif isinstance(payload, list):
        raw_results = payload
    else:
        raw_results = []
    results: list[dict[str, str]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        snippet = str(item.get("snippet") or item.get("content") or item.get("summary") or "").strip()
        if title or url or snippet:
            results.append({"title": title, "url": url, "snippet": snippet})
    results.sort(key=_evidence_priority)
    return results[:5]


def _candidate_papers_from_evidence(
    evidence: list[dict[str, str]],
    suggestions: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    if suggestions and suggestions.get("title"):
        candidates.append(
            {
                "title": str(suggestions.get("title") or ""),
                "authors": suggestions.get("authors") if isinstance(suggestions.get("authors"), list) else [],
                "year": suggestions.get("year"),
                "venue": str(suggestions.get("venue") or ""),
                "doi": str(suggestions.get("doi") or ""),
                "arxiv_id": str(suggestions.get("arxiv_id") or ""),
                "source_url": str(suggestions.get("source_url") or ""),
                "abstract": clean_abstract(suggestions.get("abstract")),
                "keywords": suggestions.get("keywords") if isinstance(suggestions.get("keywords"), list) else [],
                "confidence": float(suggestions.get("confidence") or 0.0),
                "source": "llm_suggestion",
                "notes": str(suggestions.get("notes") or ""),
            }
        )
    for index, item in enumerate(evidence):
        title = _clean_evidence_title(item.get("title", ""))
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        abstract = clean_abstract(snippet)
        if not title and not url:
            continue
        candidates.append(
            {
                "title": title,
                "authors": [],
                "year": _extract_year(f"{title} {snippet}"),
                "venue": _extract_venue_hint(f"{title} {snippet}"),
                "doi": _extract_doi(f"{title} {snippet} {url}"),
                "arxiv_id": _extract_arxiv_id(f"{title} {snippet} {url}"),
                "source_url": url,
                "abstract": abstract,
                "keywords": [],
                "confidence": max(0.3, 0.7 - index * 0.1),
                "source": "web_search",
                "notes": "Search result candidate; verify before applying.",
            }
        )
    return candidates[:6]


def _clean_evidence_title(value: str) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    title = re.sub(r"\s*[-|]\s*(arXiv|Google Scholar|Semantic Scholar|ResearchGate).*$", "", title, flags=re.IGNORECASE)
    return normalize_paper_title(title, from_filename=False) or title[:500]


def _extract_year(value: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", value or "")
    return int(match.group(0)) if match else None


def _extract_venue_hint(value: str) -> str:
    text = value or ""
    for venue in ["ICLR", "NeurIPS", "ICML", "AAAI", "IJCAI", "JCP", "JMLR", "SIAM", "Nature", "Science"]:
        if re.search(rf"\b{re.escape(venue)}\b", text, re.IGNORECASE):
            return venue
    return ""


def _extract_doi(value: str) -> str:
    match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", value or "")
    return match.group(0).rstrip(").,;") if match else ""


def _extract_arxiv_id(value: str) -> str:
    match = re.search(r"(?:arxiv\.org/(?:abs|pdf)/|arXiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", value or "", re.IGNORECASE)
    return match.group(1) if match else ""


def _evidence_priority(item: dict[str, str]) -> int:
    url = item.get("url", "").lower()
    title = item.get("title", "").lower()
    if "arxiv.org/abs/" in url or "doi.org/" in url:
        return 0
    if "arxiv" in url or "doi" in url or "arxiv" in title or "doi" in title:
        return 1
    return 2


def _build_metadata_messages(paper: Paper, evidence: list[dict[str, str]]) -> list[dict[str, str]]:
    evidence_text = "\n".join(
        f"- title: {item.get('title', '')}\n  url: {item.get('url', '')}\n  snippet: {item.get('snippet', '')}"
        for item in evidence
    )
    system_prompt = (
        "You are an evidence-first academic paper metadata assistant. Use only the current paper fields "
        "and the supplied search evidence. Prefer arXiv/DOI pages and official paper pages over secondary "
        "pages. Each evidence item is preserved as title/url/snippet; cite uncertainty in notes instead of "
        "guessing. Return only one JSON object, with no Markdown. Required fields: title, authors, year, "
        "venue, doi, arxiv_id, source_url, abstract, keywords, confidence, notes. The title must be the "
        "complete paper title when evidence supports it. Return a complete abstract only when the evidence contains "
        "abstract-like evidence from the paper itself, such as an arXiv/DOI abstract or a snippet explicitly "
        "marked Abstract/Summary. Do not place search snippets, citation text, venue notes, author blocks, "
        "or page descriptions in abstract. If evidence is insufficient, leave abstract empty and explain the "
        "gap in notes. Keywords must be "
        "3-8 English academic keywords. Do not output Chinese keywords. do not invent authors, years, venues, DOI, arXiv IDs, source URLs, abstracts, "
        "or keywords. Use empty strings, empty arrays, or null for unverified fields."
    )
    user_prompt = (
        f"Current title: {paper.title}\n"
        f"Current DOI: {paper.doi}\n"
        f"Current arXiv ID: {paper.arxiv_id}\n"
        f"Current source URL: {paper.source_url}\n\n"
        f"Search evidence:\n{evidence_text}"
    )
    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]


def _parse_json_object(value: str) -> dict[str, object]:
    text = value.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetadataSuggestionUnavailable("Model did not return valid JSON metadata.") from exc
    if not isinstance(payload, dict):
        raise MetadataSuggestionUnavailable("Model metadata response must be a JSON object.")
    return payload


def _normalize_suggestions(payload: dict[str, object]) -> dict[str, object]:
    suggestions = dict(SUGGESTION_FIELDS)
    for key in suggestions:
        if key in payload:
            suggestions[key] = payload[key]
    suggestions["title"] = _normalize_suggested_title(suggestions["title"])
    suggestions["authors"] = _normalize_authors(suggestions["authors"])
    try:
        suggestions["year"] = int(suggestions["year"]) if suggestions["year"] else None
    except (TypeError, ValueError):
        suggestions["year"] = None
    for key in ["venue", "doi", "arxiv_id", "source_url", "abstract", "notes"]:
        suggestions[key] = str(suggestions[key] or "").strip()
    original_abstract = suggestions["abstract"]
    suggestions["abstract"] = clean_abstract(original_abstract)
    if original_abstract and not suggestions["abstract"]:
        suggestions["notes"] = _append_note(
            suggestions["notes"],
            "Rejected abstract because it was not verified paper-abstract text.",
        )
    suggestions["keywords"] = _normalize_keywords(suggestions["keywords"])
    try:
        suggestions["confidence"] = float(suggestions["confidence"] or 0.0)
    except (TypeError, ValueError):
        suggestions["confidence"] = 0.0
    suggestions["confidence"] = max(0.0, min(1.0, suggestions["confidence"]))
    return suggestions


def _normalize_suggested_title(value: object) -> str:
    raw = str(value or "").strip()
    raw = re.sub(
        r"^(?:published as|accepted as|accepted at|under review|conference paper)\b.*?\b(?:20\d{2}|19\d{2})\s+",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    normalized = normalize_paper_title(raw, from_filename=False)
    if normalized:
        return normalized[:500]
    return str(value or "").strip()[:500]


def _normalize_authors(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return split_authors(value)
    return []


def _normalize_keywords(value: object) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        raw_items = [item.strip() for item in re.split(r"[,，;；、\n]+", value) if item.strip()]
    else:
        raw_items = []
    return canonical_keyword_names(raw_items)


def _append_note(notes: object, message: str) -> str:
    current = str(notes or "").strip()
    if not current:
        return message
    if message in current:
        return current
    return f"{current} {message}"
