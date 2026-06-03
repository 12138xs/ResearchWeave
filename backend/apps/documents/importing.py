from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone

from apps.ai.minimax import call_minimax_chat
from apps.documents.models import Document, DocumentImportCandidate, DocumentVersion
from apps.documents.services.keywords import set_document_keywords

BLOCKED_HOSTS = {"localhost"}
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


@dataclass(frozen=True)
class ParsedDraft:
    title: str
    summary: str
    markdown: str
    keywords: list[str]
    quality_notes: str
    confidence: float


def is_safe_external_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except (TypeError, ValueError):
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host in BLOCKED_HOSTS:
        return False
    try:
        addresses = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except ValueError:
            return False
        if _is_blocked_ip(ip):
            return False
    return True


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if any(ip in network for network in BLOCKED_NETWORKS):
        return True
    mapped_ipv4 = getattr(ip, "ipv4_mapped", None)
    if mapped_ipv4 is not None:
        return (
            any(mapped_ipv4 in network for network in BLOCKED_NETWORKS)
            or mapped_ipv4.is_multicast
            or not mapped_ipv4.is_global
        )
    return ip.is_multicast or not ip.is_global


def parse_ai_draft_payload(payload: dict[str, object]) -> ParsedDraft:
    title = str(payload.get("title", "")).strip()
    summary = str(payload.get("summary", "")).strip()
    markdown = str(payload.get("markdown", "")).strip()
    raw_keywords = payload.get("keywords", [])
    quality_notes = str(payload.get("quality_notes", "")).strip()
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    if not title:
        raise ValueError("AI draft is missing title.")
    if not markdown:
        raise ValueError("AI draft is missing markdown.")
    if not isinstance(raw_keywords, list):
        raw_keywords = []
    keywords = [str(item).strip() for item in raw_keywords if str(item).strip()]
    return ParsedDraft(
        title=title,
        summary=summary,
        markdown=markdown,
        keywords=keywords,
        quality_notes=quality_notes,
        confidence=max(0.0, min(confidence, 1.0)),
    )


def build_document_draft_messages(
    source_title: str,
    source_text: str,
    source_attribution: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是 AI for PDEs 团队知识库的中文知识整理助手。"
                "你只能生成候选草稿，不能声称内容已经发布。"
                "请用自然、专业、简洁的中文写作，不要逐字搬运外部资料。"
                "输出必须是 JSON，字段为 title, summary, markdown, keywords, quality_notes, confidence。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"资料标题：{source_title}\n"
                f"来源说明：{source_attribution}\n"
                "请把以下资料整理为团队知识库 Markdown 笔记。结构包括："
                "这篇笔记解决什么问题、核心概念、关键步骤、常见错误、延伸阅读。\n\n"
                f"{source_text[:12000]}"
            ),
        },
    ]


def generate_candidate_from_text(
    source_title: str,
    source_text: str,
    source_attribution: str,
) -> ParsedDraft:
    response = call_minimax_chat(
        build_document_draft_messages(source_title, source_text, source_attribution)
    )
    try:
        payload = json.loads(_extract_json_object(response.content))
    except json.JSONDecodeError as exc:
        raise ValueError("AI draft response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("AI draft response was not a JSON object.")
    return parse_ai_draft_payload(payload)


def _extract_json_object(content: str) -> str:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    start = cleaned.find("{")
    while start != -1:
        try:
            _, end = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            start = cleaned.find("{", start + 1)
            continue
        return cleaned[start : start + end]
    return cleaned


@transaction.atomic
def approve_candidate(candidate: DocumentImportCandidate, reviewer=None) -> Document:
    candidate = (
        DocumentImportCandidate.objects.select_for_update(of=("self",))
        .select_related("source", "target_space")
        .get(pk=candidate.pk)
    )
    if candidate.document_id:
        raise ValueError("Candidate has already been imported.")
    if candidate.status not in {
        DocumentImportCandidate.Status.NEEDS_REVIEW,
        DocumentImportCandidate.Status.APPROVED,
    }:
        raise ValueError("Only reviewable candidates can be approved.")

    document = Document.objects.create(
        title=candidate.proposed_title,
        summary=candidate.proposed_summary,
        status=Document.Status.DRAFT,
        space=candidate.target_space,
    )
    DocumentVersion.objects.create(
        document=document,
        version=1,
        markdown=candidate.proposed_markdown,
        is_current=True,
    )
    set_document_keywords(document, candidate.proposed_keywords)

    if candidate.source_id:
        candidate.source.document = document
        candidate.source.save(update_fields=["document", "updated_at"])

    candidate.document = document
    candidate.status = DocumentImportCandidate.Status.IMPORTED
    candidate.reviewed_by = reviewer
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["document", "status", "reviewed_by", "reviewed_at"])
    return document
