from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from pypdf import PdfReader

from apps.ai.minimax import call_minimax_chat
from apps.papers.models import Paper
from apps.storage.provider import get_storage_provider


@dataclass(frozen=True)
class DeepParserInput:
    paper_id: int
    title: str
    abstract: str
    source_pdf_path: str
    guidance: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_paper(cls, paper: Paper, *, guidance: str = "") -> "DeepParserInput":
        return cls(
            paper_id=paper.id,
            title=paper.title,
            abstract=paper.abstract,
            source_pdf_path=paper.source_pdf_path,
            guidance=_clean_guidance(guidance),
            metadata={
                "year": paper.year,
                "venue": paper.venue,
                "doi": paper.doi,
                "arxiv_id": paper.arxiv_id,
            },
        )


@dataclass(frozen=True)
class DeepParseResult:
    parser_name: str
    summary: str
    sections: list[dict[str, object]]
    figures: list[dict[str, object]]
    formulas: list[dict[str, object]]
    code_suggestions: list[dict[str, object]]
    reproduction_notes: str


class PlaceholderDeepParserProvider:
    parser_name = "placeholder_deep_v1"

    def parse(self, parser_input: DeepParserInput) -> DeepParseResult:
        result = DeepParseResult(
            parser_name=self.parser_name,
            summary=(
                "深度处理占位结果。后续解析器可以沿用相同任务、API 与 profile 合约，"
                "替换为真实的论文细读内容。"
            ),
            sections=[
                {
                    "index": 1,
                    "title": "结构化章节占位",
                    "page_start": None,
                    "page_end": None,
                    "summary": f"等待解析器从《{parser_input.title}》中抽取真实章节。",
                }
            ],
            figures=[],
            formulas=[],
            code_suggestions=[
                {
                    "title": "复现入口占位",
                    "note": "后续解析器可附加官方代码、环境、数据集与实验配置说明。",
                }
            ],
            reproduction_notes="占位结果仅用于验证工作流，不应作为论文精读结论。",
        )
        return _with_quality_score(result, parser_input=parser_input, provider_mode="placeholder")


class LocalPdfDeepParserProvider:
    parser_name = "local_pdf_deep_v1"
    llm_parser_name = "minimax_deep_reading_v1"

    def parse(self, parser_input: DeepParserInput) -> DeepParseResult:
        pdf_path = get_storage_provider().resolve(parser_input.source_pdf_path)
        pages = _extract_pdf_pages(pdf_path)
        full_text = _normalize_text("\n".join(str(page["text"]) for page in pages))
        if not full_text:
            raise ValueError("Deep parser could not extract text from PDF.")

        figures = _extract_figures(full_text)
        formulas = _extract_formulas(full_text)
        llm_error = ""
        try:
            result = _generate_llm_deep_result(
                parser_input=parser_input,
                pages=pages,
                full_text=full_text,
                figures=figures,
                formulas=formulas,
            )
            return _with_quality_score(result, parser_input=parser_input, provider_mode="llm")
        except Exception as exc:
            llm_error = str(exc)

        fallback = _build_rule_based_result(
            parser_input=parser_input,
            pages=pages,
            full_text=full_text,
            figures=figures,
            formulas=formulas,
        )
        return _with_quality_score(
            fallback,
            parser_input=parser_input,
            provider_mode="rule_based_fallback",
            llm_error=llm_error,
        )


RuleBasedDeepParserProvider = LocalPdfDeepParserProvider


def get_deep_parser_provider():
    provider_name = getattr(settings, "PAPER_DEEP_PARSER_PROVIDER", "local_pdf")
    if provider_name in {"placeholder", "rule_based", "local_pdf"}:
        return LocalPdfDeepParserProvider()
    if provider_name == "placeholder_legacy":
        return PlaceholderDeepParserProvider()
    raise ValueError(f"Unsupported deep parser provider: {provider_name}")


DEEP_SECTION_SPECS: list[dict[str, Any]] = [
    {
        "title": "\u5f15\u8a00\u4e0e\u7814\u7a76\u80cc\u666f",
        "aliases": ["\u5f15\u8a00", "\u7814\u7a76\u80cc\u666f", "\u80cc\u666f", "introduction", "background"],
        "needles": ["abstract", "introduction", "motivation", "challenge", "problem", "pde", "physics-informed"],
        "focus": "\u7814\u7a76\u95ee\u9898\u3001\u9886\u57df\u80cc\u666f\u3001\u5df2\u6709\u65b9\u6cd5\u75db\u70b9\u3001\u672c\u6587\u76ee\u6807\u3001\u4e3b\u8981\u8d21\u732e\u4e0e\u9002\u7528\u573a\u666f\u3002",
        "missing": "\u5f15\u8a00\u3001\u76f8\u5173\u5de5\u4f5c\u3001\u7814\u7a76\u76ee\u6807\u3001\u75db\u70b9\u548c\u8d21\u732e\u8fb9\u754c\u3002",
        "verify": "\u56de\u5230\u6458\u8981\u3001\u5f15\u8a00\u548c\u76f8\u5173\u5de5\u4f5c\uff0c\u6838\u5bf9\u4f5c\u8005\u5b9e\u9645\u58f0\u79f0\u7684\u7814\u7a76\u7f3a\u53e3\u3001\u95ee\u9898\u5b9a\u4e49\u548c\u9002\u7528\u8303\u56f4\u3002",
    },
    {
        "title": "\u65b9\u6cd5\u4ecb\u7ecd",
        "aliases": ["\u65b9\u6cd5\u8bba", "\u6280\u672f\u8def\u7ebf", "\u65b9\u6cd5\u4ecb\u7ecd", "\u65b9\u6cd5", "method", "methodology", "approach"],
        "needles": ["method", "model", "framework", "architecture", "pipeline", "loss", "boundary", "equation"],
        "focus": "\u6838\u5fc3\u65b9\u6cd5\u3001\u6a21\u578b\u7ed3\u6784\u3001\u7b97\u6cd5\u6d41\u7a0b\u3001\u516c\u5f0f/\u635f\u5931\u3001\u7269\u7406\u7ea6\u675f\u3001\u8bad\u7ec3\u4e0e\u63a8\u7406\u6d41\u7a0b\u3002",
        "missing": "\u5b8c\u6574 pipeline\u3001\u5173\u952e\u516c\u5f0f\u3001\u635f\u5931\u9879\u3001\u7ea6\u675f\u5d4c\u5165\u65b9\u5f0f\u3001\u8d85\u53c2\u6570\u548c\u5b9e\u73b0\u8fb9\u754c\u3002",
        "verify": "\u7ed3\u5408\u65b9\u6cd5\u7ae0\u8282\u3001\u516c\u5f0f\u3001\u7b97\u6cd5\u6846\u3001\u56fe\u793a\u548c\u5b98\u65b9\u5b9e\u73b0\uff0c\u8fd8\u539f\u53ef\u590d\u73b0\u7684\u6280\u672f\u8def\u7ebf\u3002",
    },
    {
        "title": "\u6838\u5fc3\u7ed3\u679c\u4e0e\u7ed3\u8bba",
        "aliases": ["\u6838\u5fc3\u7ed3\u679c", "\u4e3b\u8981\u7ed3\u679c", "\u7ed3\u679c", "\u5b9e\u9a8c", "\u7ed3\u8bba", "results", "experiments", "conclusion"],
        "needles": ["experiment", "evaluation", "result", "benchmark", "ablation", "error", "accuracy", "dataset", "metric", "conclusion"],
        "focus": "\u5b9e\u9a8c\u8bbe\u7f6e\u3001\u6570\u636e\u96c6/\u57fa\u51c6\u3001\u6307\u6807\u3001\u56fe\u8868\u8bc1\u636e\u3001\u6d88\u878d\u3001\u4e3b\u8981\u53d1\u73b0\u548c\u7ed3\u8bba\u8fb9\u754c\u3002",
        "missing": "\u57fa\u7ebf\u3001\u6307\u6807\u3001\u91cf\u5316\u7ed3\u679c\u3001\u56fe\u8868\u7f16\u53f7\u3001\u6d88\u878d\u8bbe\u7f6e\u3001\u5931\u8d25\u6848\u4f8b\u548c\u4f5c\u8005\u7ed3\u8bba\u3002",
        "verify": "\u6838\u5bf9\u56fe\u8868\u3001\u8868\u683c\u3001\u6307\u6807\u5b9a\u4e49\u3001\u6570\u636e\u5212\u5206\u3001\u6d88\u878d\u8bbe\u7f6e\u4e0e\u7ed3\u8bba\u662f\u5426\u88ab\u8bc1\u636e\u652f\u6491\u3002",
    },
    {
        "title": "\u603b\u7ed3",
        "aliases": ["\u6279\u5224\u6027\u603b\u7ed3", "\u590d\u73b0\u5efa\u8bae", "\u603b\u7ed3", "\u5c40\u9650", "\u8ba8\u8bba", "summary", "discussion", "limitation", "reproduction"],
        "needles": ["conclusion", "discussion", "limitation", "future work", "failure", "constraint", "assumption", "sensitivity"],
        "focus": "\u8bba\u6587\u8d21\u732e\u8fb9\u754c\u3001\u5c40\u9650\u6027\u3001\u98ce\u9669\u70b9\u3001\u53ef\u590d\u73b0\u6027\u3001\u4f18\u5148\u590d\u73b0\u5b9e\u9a8c\u4e0e\u540e\u7eed\u9605\u8bfb\u5efa\u8bae\u3002",
        "missing": "\u4f5c\u8005\u81ea\u8ff0\u5c40\u9650\u3001\u5931\u8d25\u6848\u4f8b\u3001\u6cdb\u5316\u8303\u56f4\u3001\u590d\u73b0\u5b9e\u9a8c\u6e05\u5355\u548c\u540e\u7eed\u5de5\u4f5c\u3002",
        "verify": "\u533a\u5206\u4f5c\u8005\u539f\u6587\u4e0e\u8bfb\u8005\u63a8\u65ad\uff0c\u590d\u73b0\u524d\u6838\u5bf9\u6570\u636e\u3001\u89c4\u6a21\u3001\u8fb9\u754c\u6761\u4ef6\u3001\u968f\u673a\u6027\u548c\u8ba1\u7b97\u9884\u7b97\u3002",
    },
]
FORBIDDEN_QUALITY_TERMS = ["pypdf", "upload", "storage", "placeholder"]


def _extract_pdf_pages(pdf_path: Path) -> list[dict[str, object]]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF does not exist: {pdf_path}")
    reader = PdfReader(str(pdf_path))
    pages: list[dict[str, object]] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append({"page": index, "text": page.extract_text() or ""})
    return pages


def _generate_llm_deep_result(
    *,
    parser_input: DeepParserInput,
    pages: list[dict[str, object]],
    full_text: str,
    figures: list[dict[str, object]],
    formulas: list[dict[str, object]],
) -> DeepParseResult:
    response = call_minimax_chat(
        _build_llm_messages(parser_input=parser_input, pages=pages, full_text=full_text),
        max_tokens=int(getattr(settings, "PAPER_DEEP_LLM_MAX_TOKENS", 5200)),
        temperature=0.18,
        timeout=int(getattr(settings, "PAPER_DEEP_LLM_TIMEOUT_SECONDS", 180)),
    )
    content = _llm_response_content(response)
    if not _llm_has_expected_deep_headings(content):
        raise ValueError("MiniMax deep reading response missed the required section headings.")
    sections = _parse_llm_sections(content, pages=pages, full_text=full_text)
    if not any(str(section.get("summary", "")).strip() for section in sections):
        raise ValueError("MiniMax deep reading response did not contain usable sections.")

    return DeepParseResult(
        parser_name=LocalPdfDeepParserProvider.llm_parser_name,
        summary=_build_llm_summary(parser_input, sections),
        sections=sections,
        figures=figures,
        formulas=formulas,
        code_suggestions=_build_code_suggestions(full_text, parser_input),
        reproduction_notes=_build_reproduction_notes(parser_input, pages, figures, formulas),
    )


def _build_llm_messages(
    *,
    parser_input: DeepParserInput,
    pages: list[dict[str, object]],
    full_text: str,
) -> list[dict[str, str]]:
    metadata_lines = [
        f"- {key}: {value}"
        for key, value in parser_input.metadata.items()
        if value not in (None, "", [])
    ]
    excerpt = _build_llm_excerpt(full_text, pages)
    section_titles = [str(spec["title"]) for spec in DEEP_SECTION_SPECS]
    guidance = _clean_guidance(parser_input.guidance)
    system_prompt = (
        "You are the A510 Knowledge Base deep-reading assistant for an AI for PDEs research team. "
        "Write a rigorous Chinese Markdown deep-reading note based only on the title, abstract, metadata, and extracted paper text. "
        "Do not mention parser libraries, file paths, upload/storage implementation, or system internals. "
        "Use the following four level-2 headings exactly and no other level-2 headings:\n"
        + "\n".join(f"## {title}" for title in section_titles)
        + "\n\nQuality requirements: each section should contain at least three substantial Chinese paragraphs. "
        "Inside every required level-2 section, use these level-3 subsections in Chinese: "
        "### 原文直译式要点, ### 梳理与扩展, and ### 核对建议. "
        "The methodology section may additionally include ### 算法/流程草图 with a fenced text block when the paper gives enough method evidence. "
        "Cover introduction/background, methodology, experiments/results, conclusion, limitations, and reproduction risks. "
        "The methodology section must explain intuition, pipeline, equations/loss/constraints, training or inference steps, and can include a fenced text algorithm. "
        "The results section must discuss datasets/benchmarks, metrics, figure/table evidence, main findings, and evidence boundaries. "
        "The final section must separate author claims from reader inference, and list reproducibility checks including data, configs, randomness, compute budget, risks, and manual verification. "
        "Use formulas, lists, and code blocks when helpful. If evidence is insufficient, explicitly say that the original evidence is insufficient and must be checked. Do not invent numbers. "
        "Do not include chain-of-thought, reasoning process narration, or planning sentences. "
        "Do not paste long English source paragraphs; write user-facing content in Chinese and keep only necessary English terms, paper titles, variable names, and short quoted technical phrases. "
        "If a user reading guidance is provided, use it only to adjust emphasis and depth allocation inside the fixed template; never change, remove, rename, or reorder the required four level-2 headings."
    )
    user_prompt = (
        f"Title: {parser_input.title or 'unknown'}\n\n"
        f"Abstract: {parser_input.abstract.strip() or 'No abstract provided; reason conservatively from the text.'}\n\n"
        f"Metadata:\n{chr(10).join(metadata_lines) if metadata_lines else '- none'}\n\n"
        f"User reading guidance: {guidance or 'none'}\n\n"
        "Extracted text excerpts with page hints follow. Page hints are only evidence anchors; do not discuss extraction mechanics in the final answer.\n\n"
        f"{excerpt}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

def _llm_response_content(response: object) -> str:
    if isinstance(response, str):
        return response
    return str(getattr(response, "content", "") or "")


def _clean_guidance(value: str) -> str:
    return " ".join(str(value or "").strip().split())[:500]


def _llm_has_expected_deep_headings(content: str) -> bool:
    sections = _split_deep_markdown_sections(content)
    return all(str(spec["title"]) in sections for spec in DEEP_SECTION_SPECS)


def _build_llm_excerpt(full_text: str, pages: list[dict[str, object]]) -> str:
    page_records = [
        {
            "page": page.get("page"),
            "text": _normalize_text(str(page.get("text", ""))),
        }
        for page in pages
        if str(page.get("text", "")).strip()
    ]
    if not page_records:
        return full_text[: int(getattr(settings, "PAPER_DEEP_LLM_EXCERPT_MAX_CHARS", 32000))]

    excerpt_limit = int(getattr(settings, "PAPER_DEEP_LLM_EXCERPT_MAX_CHARS", 32000))
    intro = _join_page_slice(page_records[:4], max_chars=8000)
    middle = _keyword_excerpt(
        page_records,
        ["method", "model", "framework", "architecture", "loss", "algorithm", "equation", "boundary"],
        max_chars=9000,
    )
    results = _keyword_excerpt(
        page_records,
        ["experiment", "result", "benchmark", "ablation", "metric", "error", "accuracy", "dataset", "table", "figure"],
        max_chars=9000,
    )
    ending = _join_page_slice(page_records[-3:], max_chars=6000)
    blocks = [
        ("开头/引言附近文本", intro),
        ("方法相关候选文本", middle),
        ("实验与结果相关候选文本", results),
        ("结论/文末附近文本", ending),
    ]
    rendered = []
    seen: set[str] = set()
    for label, text in blocks:
        cleaned = text.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        rendered.append(f"### {label}\n{cleaned}")
    if not rendered:
        return full_text[:excerpt_limit]
    return "\n\n".join(rendered)[:excerpt_limit]


def _join_page_slice(page_records: list[dict[str, object]], *, max_chars: int) -> str:
    parts = []
    for record in page_records:
        page = record.get("page")
        parts.append(f"[Page {page}]\n{str(record.get('text', '')).strip()}")
    return "\n\n".join(parts)[:max_chars]


def _keyword_excerpt(page_records: list[dict[str, object]], needles: list[str], *, max_chars: int) -> str:
    selected = []
    for record in page_records:
        text = str(record.get("text", ""))
        lowered = text.lower()
        if any(needle in lowered for needle in needles):
            selected.append(
                f"[Page {record.get('page')}]\n{_summarize_text(text, max_chars=1800)}"
            )
        if len("\n\n".join(selected)) >= max_chars:
            break
    return "\n\n".join(selected)[:max_chars]


def _parse_llm_sections(content: str, *, pages: list[dict[str, object]], full_text: str) -> list[dict[str, object]]:
    markdown_sections = _split_deep_markdown_sections(content)
    sentence_records = _sentence_records(pages)
    sections: list[dict[str, object]] = []
    for index, spec in enumerate(DEEP_SECTION_SPECS, start=1):
        title = str(spec["title"])
        summary = markdown_sections.get(title, "").strip()
        if not summary:
            for alias in spec["aliases"]:
                summary = markdown_sections.get(str(alias), "").strip()
                if summary:
                    break
        summary = _clean_section_markdown(summary, title=title)
        evidence = _evidence_for_needles(sentence_records, spec["needles"], limit=8)
        has_direct_evidence = bool(evidence)
        if not evidence:
            evidence = _general_evidence(sentence_records, index=index, limit=4)
        page_numbers = [item["page"] for item in evidence if isinstance(item.get("page"), int)]
        if not summary:
            summary = _section_summary_from_evidence(
                title=title,
                evidence=evidence,
                has_direct_evidence=has_direct_evidence,
                focus=str(spec["focus"]),
                missing=str(spec["missing"]),
                verify=str(spec["verify"]),
            )
        else:
            summary = _ensure_deep_section_depth(summary, spec=spec, evidence=evidence)
        sections.append(
            {
                "index": index,
                "title": title,
                "page_start": min(page_numbers) if page_numbers else None,
                "page_end": max(page_numbers) if page_numbers else None,
                "summary": summary,
                "evidence": evidence,
                "confidence": _section_confidence(full_text, spec["needles"], has_direct_evidence),
                "missing_or_next_check": "" if has_direct_evidence else f"缺少直接证据：{spec['missing']}。建议核对：{spec['verify']}",
            }
        )
    return sections


def _split_deep_markdown_sections(content: str) -> dict[str, str]:
    cleaned = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE | re.DOTALL)
    title_pattern = "|".join(re.escape(str(item["title"])) for item in DEEP_SECTION_SPECS)
    alias_pattern = "|".join(
        re.escape(str(alias))
        for item in DEEP_SECTION_SPECS
        for alias in item["aliases"]
    )
    pattern = re.compile(rf"(?im)^#{{1,3}}\s*({title_pattern}|{alias_pattern})\s*$")
    matches = list(pattern.finditer(cleaned))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        heading = match.group(1).strip()
        canonical = _canonical_section_title(heading)
        sections[canonical] = cleaned[start:end].strip()
    if not sections:
        sections[DEEP_SECTION_SPECS[0]["title"]] = cleaned
    return sections


def _canonical_section_title(value: str) -> str:
    cleaned = value.strip().lower()
    for spec in DEEP_SECTION_SPECS:
        title = str(spec["title"])
        if cleaned == title.lower() or cleaned in {str(alias).lower() for alias in spec["aliases"]}:
            return title
    return value.strip()


def _clean_section_markdown(value: str, *, title: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    cleaned = re.sub(rf"(?im)^\s*#{{1,6}}\s*{re.escape(title)}\s*$", "", cleaned).strip()
    cleaned = _remove_reasoning_leakage(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = _wrap_bare_tex_commands(cleaned)
    return cleaned.strip()


def _remove_reasoning_leakage(markdown: str) -> str:
    leakage_line = re.compile(
        r"(?im)^\s*(?:"
        r"now,?\s+i\s+need\s+to\b|"
        r"i\s+need\s+to\b|"
        r"i\s+should\b|"
        r"however,\s+i\s+should\b|"
        r"in\s+the\s+(?:['\"“]?[^'\n\"”]{1,80}['\"”]?\s+)?section\b|"
        r"the\s+instruction\s+says\b|"
        r"the\s+prompt\s+(?:asks|requires|says)\b|"
        r"let'?s\s+(?:craft|write|ensure|produce)\b|"
        r"the\s+user\s+(?:wants|asks|requested)\b|"
        r"we\s+need\s+to\s+ensure\b"
        r").*$"
    )
    cleaned = leakage_line.sub("", markdown)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _wrap_bare_tex_commands(markdown: str) -> str:
    protected_pattern = re.compile(r"```.*?```|`[^`\n]+`|\$\$.*?\$\$|\$[^$\n]+\$", flags=re.DOTALL)
    pieces: list[str] = []
    cursor = 0
    for match in protected_pattern.finditer(markdown):
        pieces.append(_wrap_tex_in_plain_text(markdown[cursor : match.start()]))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(_wrap_tex_in_plain_text(markdown[cursor:]))
    return "".join(pieces)


def _wrap_tex_in_plain_text(text: str) -> str:
    long_equation_pattern = re.compile(
        r"\b[A-Za-z\\][A-Za-z0-9_{}^\\]*(?:\([^.\n。；;]*\))?\s*=\s*(?:\[[^\]\n]+\]|[^.\n。；;]+)"
    )
    tex_command_pattern = re.compile(
        r"\\frac\{[^{}\n]+\}\{[^{}\n]+\}|"
        r"\\mathcal\{[^{}\n]+\}(?:[_^]\{?[A-Za-z0-9_\\]+\}?)?|"
        r"(?<![A-Za-z0-9_{}^\\])\\(?:theta|alpha|beta|gamma|lambda|mu|nu|phi|psi|omega|rho|sigma|tau|epsilon|eta|xi|zeta|Delta|Theta|Phi|Psi|Omega)\b|"
        r"\\(?:partial|nabla)(?:[_^]\{?[A-Za-z0-9_\\]+\}?)*(?:\s+[A-Za-z][A-Za-z0-9_{}^\\]*(?:\([^)\n]*\))?)?|"
        r"\\(?:sum|int)(?:[_^]\{?[A-Za-z0-9_=+\-\\]+\}?)*(?:\s*[A-Za-z0-9_{}^\\=+\-*/().]+)?"
    )
    scripted_token_pattern = re.compile(
        r"\b(?:[A-Za-z]_\{?\\?[A-Za-z0-9]+\}?|[A-Za-z]\^\{?[A-Za-z0-9]+\}?|[A-Z][A-Za-z0-9]*_\{?\\?[A-Za-z0-9]+\}?)"
        r"(?:[_^]\{?\\?[A-Za-z0-9]+\}?)*"
    )

    wrapped = _wrap_unprotected_math(text, long_equation_pattern, trim=True)
    wrapped = _wrap_unprotected_math(wrapped, tex_command_pattern)
    wrapped = _wrap_unprotected_math(wrapped, scripted_token_pattern)
    return wrapped


def _wrap_unprotected_math(text: str, pattern: re.Pattern[str], *, trim: bool = False) -> str:
    protected_pattern = re.compile(r"\$\$.*?\$\$|\$[^$\n]+\$", flags=re.DOTALL)
    pieces: list[str] = []
    cursor = 0
    for protected in protected_pattern.finditer(text):
        pieces.append(_wrap_math_matches(text[cursor : protected.start()], pattern, trim=trim))
        pieces.append(protected.group(0))
        cursor = protected.end()
    pieces.append(_wrap_math_matches(text[cursor:], pattern, trim=trim))
    return "".join(pieces)


def _wrap_math_matches(text: str, pattern: re.Pattern[str], *, trim: bool) -> str:
    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0).strip()
        if trim:
            candidate = _trim_formula_candidate(candidate)
        if not _looks_like_math_fragment(candidate):
            return match.group(0)
        prefix_len = len(match.group(0)) - len(match.group(0).lstrip())
        suffix = match.group(0)[prefix_len + len(candidate) :]
        return f"{match.group(0)[:prefix_len]}${candidate}${suffix}"

    return pattern.sub(replace, text)


def _trim_formula_candidate(candidate: str) -> str:
    trimmed = candidate.rstrip(" ,。.;；:")
    split = re.search(r"\s+(?:should|when|while|where|without|during|because|which|that)\b", trimmed)
    if split:
        trimmed = trimmed[: split.start()].rstrip(" ,。.;；:")
    return trimmed


def _looks_like_math_fragment(candidate: str) -> bool:
    return bool(
        re.search(
            r"\\(?:mathcal|frac|int|sum|partial|nabla|theta|alpha|beta|gamma|lambda|mu|nu|phi|psi|omega|rho|sigma|tau|epsilon|eta|xi|zeta|Delta|Theta|Phi|Psi|Omega)\b|[_^]|=\s*\[|[=+\-*/]",
            candidate,
        )
        and re.search(r"[A-Za-z0-9\\]", candidate)
    )


def _ensure_deep_section_depth(
    summary: str,
    *,
    spec: dict[str, Any],
    evidence: list[dict[str, object]],
) -> str:
    if len(_strip_markdown(summary)) >= 280:
        return summary
    evidence_digest = _summarize_text(" ".join(str(item.get("text", "")) for item in evidence), max_chars=360)
    supplement = (
        "\n\n### 深度补充与核对\n\n"
        f"这一节还需要围绕{spec['focus']}继续展开。当前可追踪的原文线索包括：{evidence_digest or '原文证据不足，需要回到对应章节人工核对'}。"
        f"后续精读时应重点核对：{spec['verify']} "
        "如果这部分来自模型生成而证据不足，应把它作为阅读假设，而不是直接写入最终结论。"
    )
    return _wrap_bare_tex_commands(f"{summary.rstrip()}{supplement}")


def _build_llm_summary(parser_input: DeepParserInput, sections: list[dict[str, object]]) -> str:
    title = parser_input.title or "\u672a\u547d\u540d\u8bba\u6587"
    return (
        f"《{title}》的细读内容已按引言背景、方法机制、核心结果与复现边界整理；"
        "正文四节包含证据线索、公式/图表核对点和复现建议。"
    )

def _build_rule_based_result(
    *,
    parser_input: DeepParserInput,
    pages: list[dict[str, object]],
    full_text: str,
    figures: list[dict[str, object]],
    formulas: list[dict[str, object]],
) -> DeepParseResult:
    sections = _extract_sections(full_text, pages)
    return DeepParseResult(
        parser_name=LocalPdfDeepParserProvider.parser_name,
        summary=_build_summary(parser_input, full_text, sections),
        sections=sections,
        figures=figures,
        formulas=formulas,
        code_suggestions=_build_code_suggestions(full_text, parser_input),
        reproduction_notes=_build_reproduction_notes(parser_input, pages, figures, formulas),
    )


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _summarize_text(text: str, *, max_chars: int = 520) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
    return f"{truncated}."


def _strip_markdown(value: str) -> str:
    stripped = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    stripped = re.sub(r"[#>*_`|~-]+", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip()


def _extract_figures(full_text: str) -> list[dict[str, object]]:
    figures = []
    pattern = re.compile(r"(?im)\b((?:Figure|Fig\.?|Table)\s*\d+[^\n.]*[.\n][^\n]{0,260})")
    for match in pattern.finditer(full_text):
        caption = " ".join(match.group(1).split()).strip()
        lowered = caption.lower()
        note_bits = ["原文中出现图表线索，建议回到 PDF 核对图题、坐标轴和对应正文结论。"]
        if any(token in lowered for token in ("error", "accuracy", "metric", "l2", "rmse", "mae")):
            note_bits.append("该图表可能承载误差或精度对比，是判断方法有效性的关键证据。")
        if any(token in lowered for token in ("ablation", "variant", "component")):
            note_bits.append("该图表可能对应消融实验，需要确认各模块的贡献。")
        figures.append({"id": f"fig-{len(figures) + 1}", "caption": caption, "page": None, "note": " ".join(note_bits)})
    return figures[:20]

def _extract_formulas(full_text: str) -> list[dict[str, object]]:
    formulas = []
    math_pattern = re.compile(
        r"(?:[A-Za-z][A-Za-z0-9_{}^\\]*\s*[=+\-*/]\s*){2,}|"
        r"\\(?:frac|sum|int|partial|nabla)|\b(?:argmin|softmax|log)\b"
    )
    for line in full_text.splitlines():
        candidate = line.strip()
        if len(candidate) < 6 or len(candidate) > 260:
            continue
        has_equation_shape = "=" in candidate and any(token in candidate for token in ("_", "^", "+", "-", "\\", "partial", "nabla"))
        if (math_pattern.search(candidate) or has_equation_shape) and any(symbol in candidate for symbol in ("=", "+", "-", "\\", "^", "_")):
            formulas.append({
                "id": f"eq-{len(formulas) + 1}",
                "latex": _safe_latex(candidate) or candidate,
                "text": candidate,
                "note": "从正文抽取到疑似公式，请人工核对 PDF 原式并整理为标准 LaTeX。",
            })
    return formulas[:20]

def _build_code_suggestions(full_text: str, parser_input: DeepParserInput) -> list[dict[str, object]]:
    lowered = full_text.lower()
    suggestions = [{
        "title": "复现入口",
        "note": "优先查找官方仓库中的 scripts/ 与 configs/，固定数据划分、随机种子、指标口径和硬件预算。",
    }]
    if any(term in lowered for term in ("dataset", "benchmark", "burgers", "navier", "darcy", "cylinder")):
        suggestions.append({"title": "数据与基准", "note": "记录 PDE 类型、网格规模、时间步、训练/测试划分和与论文表格一致的基准设置。"})
    if any(term in lowered for term in ("metric", "relative l2", "l2 error", "rmse", "mae", "accuracy", "error")):
        suggestions.append({"title": "评价指标", "note": "复现时应同时记录相对 L2、RMSE/MAE 等指标，并说明统计方式。"})
    if any(term in lowered for term in ("ablation", "seed", "random", "hyperparameter", "learning rate", "batch size")):
        suggestions.append({"title": "消融与稳健性", "note": "单独验证关键模块、学习率、batch size、随机种子和训练轮数对结果的影响。"})
    if any(term in lowered for term in ("pde", "burgers", "navier", "physics-informed", "operator")):
        suggestions.append({"title": "PDE 约束核对", "note": "确认损失函数中的方程残差、边界条件、初始条件和物理参数是否与 configs/ 一致。"})
    if any(term in lowered for term in ("github", "code", "implementation", "repository")):
        suggestions.append({"title": "代码核验", "note": "核对官方实现的 commit、依赖版本、训练脚本入口和推理脚本，避免仅复现伪代码。"})
    if parser_input.metadata.get("doi") or parser_input.metadata.get("arxiv_id"):
        suggestions.append({"title": "外部索引", "note": "用 DOI 或 arXiv 号核对论文版本、补充材料和作者公开仓库。"})
    return suggestions

def _extract_sections(full_text: str, pages: list[dict[str, object]]) -> list[dict[str, object]]:
    sentence_records = _sentence_records(pages)
    if not sentence_records:
        sentence_records = [{"page": None, "text": _summarize_text(full_text, max_chars=420)}]

    sections: list[dict[str, object]] = []
    for index, spec in enumerate(DEEP_SECTION_SPECS, start=1):
        evidence = _evidence_for_needles(sentence_records, spec["needles"], limit=8)
        has_direct_evidence = bool(evidence)
        if not evidence:
            evidence = _general_evidence(sentence_records, index=index, limit=4)

        page_numbers = [item["page"] for item in evidence if isinstance(item.get("page"), int)]
        sections.append(
            {
                "index": index,
                "title": spec["title"],
                "page_start": min(page_numbers) if page_numbers else None,
                "page_end": max(page_numbers) if page_numbers else None,
                "summary": _section_summary_from_evidence(
                    title=str(spec["title"]),
                    evidence=evidence,
                    has_direct_evidence=has_direct_evidence,
                    focus=str(spec["focus"]),
                    missing=str(spec["missing"]),
                    verify=str(spec["verify"]),
                ),
                "evidence": evidence,
                "confidence": _section_confidence(full_text, spec["needles"], has_direct_evidence),
                "missing_or_next_check": "" if has_direct_evidence else f"缺少直接证据：{spec['missing']}。建议核对：{spec['verify']}",
            }
        )
    return sections


def _build_summary(parser_input: DeepParserInput, full_text: str, sections: list[dict[str, object]]) -> str:
    title = parser_input.title or "\u672a\u547d\u540d\u8bba\u6587"
    source = parser_input.abstract.strip() if parser_input.abstract.strip() else full_text
    opening = _summarize_text(source, max_chars=520)
    section_names = "\u3001".join(str(section.get("title", "")).strip() for section in sections if section.get("title"))
    return (
        f"《{title}》的规则兜底深度解析已围绕研究问题、方法机制、实验证据和复现边界展开。"
        f"可读文本线索显示：{opening}。"
        f"本次笔记按 {section_names} 分组组织，并尽量保留原文证据片段。"
        "由于 MiniMax 细读未能完成，当前结果需要人工复核，尤其要核对问题定义、损失函数、图表数字、基线和消融设置。"
    )

def _build_reproduction_notes(
    parser_input: DeepParserInput,
    pages: list[dict[str, object]],
    figures: list[dict[str, object]],
    formulas: list[dict[str, object]],
) -> str:
    metadata_bits = [
        f"{key}={value}"
        for key, value in parser_input.metadata.items()
        if value not in (None, "", [])
    ]
    full_text = _normalize_text("\n".join(str(page.get("text", "")) for page in pages))
    lowered = full_text.lower()
    dataset_signals = _keywords_present(
        lowered,
        ["dataset", "benchmark", "burgers", "navier-stokes", "navier", "darcy", "cylinder", "mnist", "imagenet"],
    )
    metric_signals = _keywords_present(
        lowered,
        ["metric", "relative l2", "l2 error", "rmse", "mae", "accuracy", "error", "mse"],
    )
    ablation_signals = _keywords_present(lowered, ["ablation", "variant", "component", "hyperparameter", "learning rate"])
    seed_signals = _keywords_present(lowered, ["seed", "random", "stochastic", "repeat", "standard deviation"])
    return (
        "### 复现核对清单\n\n"
        f"- 已抽取 {len(pages)} 页文本线索、{len(figures)} 条图表线索和 {len(formulas)} 条疑似公式，建议与原始 PDF 逐项核对。\n"
        f"- 数据集或基准线索：{_format_signal_list(dataset_signals)}。\n"
        f"- 评价指标线索：{_format_signal_list(metric_signals)}。\n"
        f"- 消融设置线索：{_format_signal_list(ablation_signals)}。\n"
        f"- 随机性与重复实验线索：{_format_signal_list(seed_signals)}。\n"
        "- 复现前应固定训练/测试划分、随机种子、硬件预算、PDE 参数、边界条件、损失权重，并同步记录 scripts/ 与 configs/。\n"
        f"- 元数据线索：{', '.join(metadata_bits) if metadata_bits else '缺少 DOI、arXiv 或公开仓库等外部索引'}。\n"
        "- 若当前结果来自规则兜底解析，请先人工复核公式、图表数字和实验表格，再作为正式结论引用。"
    )

def _section_summary_from_evidence(
    *,
    title: str,
    evidence: list[dict[str, object]],
    has_direct_evidence: bool,
    focus: str,
    missing: str,
    verify: str,
) -> str:
    translated_points = _translated_evidence_points(evidence)
    if not translated_points:
        translated_points = ["未抽取到足够稳定的原文句子，需回到 PDF 对该部分做人工核对。"]
    evidence_digest = _summarize_text(" ".join(str(item.get("text", "")) for item in evidence), max_chars=920)
    directness = "本节有直接关键词证据支撑。" if has_direct_evidence else "本节直接证据不足，以下内容主要来自相邻段落和全文线索。"
    method_flow = ""
    if title == str(DEEP_SECTION_SPECS[1]["title"]):
        method_flow = (
            "\n\n### 算法/流程草图\n\n"
            "```text\n"
            "1. 读取论文定义的问题、数据和物理约束，明确输入、输出和目标方程。\n"
            "2. 根据原文描述拆分模型模块、训练目标和关键超参数。\n"
            "3. 将数据项、物理残差、边界条件和正则项整理为可复现的损失结构。\n"
            "4. 对照实验表格核对 baseline、指标、消融和统计口径。\n"
            "5. 形成复现清单，并标记仍需从 PDF 或代码仓库人工确认的环节。\n"
            "```\n"
        )
    rendered = (
        "### 原文线索\n\n"
        + "\n".join(f"{idx}. {point}" for idx, point in enumerate(translated_points, start=1))
        + "\n\n### 梳理与扩展\n\n"
        f"{directness} 本节聚焦：{focus}。可抽取的核心原文片段为：{evidence_digest}。"
        "解析时应区分论文已经实证证明的结论、作者给出的解释，以及仍需复现实验验证的推断。"
        "对于 AI for PDEs 论文，还需要特别核对方程类型、边界条件、离散网格、训练数据生成协议和误差统计口径，避免把模型描述误读成可泛化结论。"
        f"{method_flow}\n\n### 核对建议\n\n"
        f"- 必须核对：{verify}\n"
        f"- 当前可能缺失：{missing}。\n"
        "- 若后续重跑 MiniMax 细读，应要求模型逐段翻译引言、方法、实验和结论，并把每个数字对应到图表或公式。"
    )
    return _wrap_bare_tex_commands(rendered)

def _translated_evidence_points(evidence: list[dict[str, object]]) -> list[str]:
    points: list[str] = []
    for item in evidence[:6]:
        text = _summarize_text(str(item.get("text", "")).strip(), max_chars=260)
        if not text:
            continue
        page = item.get("page")
        prefix = f"第 {page} 页线索" if isinstance(page, int) else "原文线索"
        lowered = text.lower()
        if any(word in lowered for word in ("abstract", "introduction", "motivation", "problem", "challenge")):
            meaning = "可理解为论文在交代研究问题、应用背景或现有方法困难。"
        elif any(word in lowered for word in ("method", "model", "framework", "loss", "boundary", "equation", "architecture")):
            meaning = "可理解为方法部分在说明模型结构、约束项或训练目标。"
        elif any(word in lowered for word in ("experiment", "result", "benchmark", "error", "accuracy", "metric", "ablation")):
            meaning = "可理解为实验部分在给出 benchmark、指标、误差或消融证据。"
        elif any(word in lowered for word in ("conclusion", "discussion", "limitation", "future")):
            meaning = "可理解为论文在总结贡献、限制或未来工作。"
        else:
            meaning = "可作为该章节的补充证据，但需要结合上下文判断。"
        points.append(f"{prefix}：{meaning}（原文：{text}）")
    return points

def _sentence_records(pages: list[dict[str, object]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for page in pages:
        page_number = page.get("page")
        text = _normalize_text(str(page.get("text", "")))
        for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", text):
            cleaned = " ".join(sentence.split()).strip()
            if len(cleaned) < 12:
                continue
            records.append(
                {
                    "page": page_number if isinstance(page_number, int) else None,
                    "text": cleaned[:720],
                }
            )
    return records


def _evidence_for_needles(
    sentence_records: list[dict[str, object]],
    needles: list[str],
    *,
    limit: int,
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    seen: set[str] = set()
    for record in sentence_records:
        text = str(record.get("text", ""))
        lowered = text.lower()
        if not any(needle in lowered for needle in needles):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        evidence.append({"page": record.get("page"), "text": text})
        if len(evidence) >= limit:
            break
    return evidence


def _general_evidence(sentence_records: list[dict[str, object]], *, index: int, limit: int) -> list[dict[str, object]]:
    if not sentence_records:
        return []
    start = min(len(sentence_records) - 1, max(0, (index - 1) * limit))
    return [
        {"page": record.get("page"), "text": str(record.get("text", ""))}
        for record in sentence_records[start : start + limit]
    ]


def _safe_latex(candidate: str) -> str:
    compact = candidate.strip()
    unicode_math_symbols = "∂∇∆Δ∑∫≈≤≥≠·ψθλμνσφρ𝜕𝜎𝜓𝜃𝜙𝜆𝜇𝜈𝜌𝛼𝛽𝛾𝛥𝑡𝑥𝑦𝑧𝐐𝐅𝐆𝐇𝐗𝐖𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
    if any(symbol in compact for symbol in unicode_math_symbols) and re.search(r"[=+\-·()]", compact):
        return compact
    if (
        re.fullmatch(r"[A-Za-z0-9_{}^\\=+\-*/().,;:\s]+", compact)
        and re.search(r"\\|[_^=+\-*/]", compact)
    ):
        return compact
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_{}^]*\s*=\s*[-+*/0-9A-Za-z_{}^().\s]+", compact):
        return compact
    return ""


def _section_confidence(full_text: str, needles: list[str], has_direct_evidence: bool) -> str:
    if not has_direct_evidence:
        return "needs_review"
    return _confidence_for_keywords(full_text, needles)


def _keywords_present(lowered_text: str, candidates: list[str]) -> list[str]:
    return [candidate for candidate in candidates if candidate in lowered_text]


def _format_signal_list(signals: list[str]) -> str:
    return "、".join(signals) if signals else "抽取文本中未明确出现，需要人工核对"


def _confidence_for_keywords(full_text: str, needles: list[str]) -> str:
    lowered = full_text.lower()
    hits = sum(1 for needle in needles if needle in lowered)
    if hits >= 3:
        return "medium"
    if hits >= 1:
        return "weak"
    return "needs_review"


def _with_quality_score(
    result: DeepParseResult,
    *,
    parser_input: DeepParserInput,
    provider_mode: str,
    llm_error: str = "",
) -> DeepParseResult:
    quality = _score_deep_parse_result(result, provider_mode=provider_mode, llm_error=llm_error)
    scored_sections = []
    for section in result.sections:
        section_quality = _score_section(section)
        scored = {
            **section,
            "quality_score": section_quality["score"],
            "quality": {
                **section_quality,
                "overall_score": quality["score"],
                "overall_needs_review": quality["needs_review"],
            },
        }
        if quality["needs_review"] and not scored.get("missing_or_next_check"):
            scored["missing_or_next_check"] = "质量评分偏低，需要人工复核。"
        scored_sections.append(scored)

    quality_note = {
        "title": "\u6df1\u5ea6\u89e3\u6790\u8d28\u91cf\u8bc4\u5206",
        "score": quality["score"],
        "note": _quality_user_note(quality, provider_mode=provider_mode, llm_error=llm_error),
        "quality": quality,
        "needs_review": quality["needs_review"],
    }
    code_suggestions = [
        item for item in result.code_suggestions if str(item.get("title")) != "\u6df1\u5ea6\u89e3\u6790\u8d28\u91cf\u8bc4\u5206"
    ]
    code_suggestions.append(quality_note)
    summary = result.summary
    if quality["needs_review"] and "needs_review" not in summary:
        summary = f"{summary}\n\nneeds_review: \u8d28\u91cf\u8bc4\u5206\u4e3a {quality['score']}\uff0c\u5efa\u8bae\u4eba\u5de5\u590d\u6838\u540e\u518d\u4f5c\u4e3a\u6b63\u5f0f\u7cbe\u8bfb\u7ed3\u8bba\u3002"
    return DeepParseResult(
        parser_name=result.parser_name,
        summary=summary,
        sections=scored_sections,
        figures=result.figures,
        formulas=result.formulas,
        code_suggestions=code_suggestions,
        reproduction_notes=result.reproduction_notes,
    )


def _quality_user_note(quality: dict[str, object], *, provider_mode: str, llm_error: str) -> str:
    score = quality.get("score")
    needs_review = bool(quality.get("needs_review"))
    if provider_mode != "llm":
        reason = "MiniMax 细读未能完成，当前结果来自规则兜底解析。"
    elif needs_review:
        reason = "本次细读内容密度或证据完整度不足。"
    else:
        reason = "本次细读达到当前质量阈值。"
    action = "建议点击“重新生成深度解析”，或人工核对后再引用。" if needs_review else "仍建议抽查公式、图表数字和复现实验设置。"
    error_note = f" 错误线索：{llm_error[:160]}" if llm_error else ""
    return f"质量评分 {score}/100。{reason}{action}{error_note}"

def _score_deep_parse_result(
    result: DeepParseResult,
    *,
    provider_mode: str,
    llm_error: str,
) -> dict[str, object]:
    section_texts = [str(section.get("summary", "")) for section in result.sections]
    all_text = "\n".join(
        [result.parser_name, result.summary, *section_texts, str(result.code_suggestions), result.reproduction_notes]
    )
    stripped = _strip_markdown(all_text)
    total_length = len(stripped)
    expected_titles = [str(spec["title"]) for spec in DEEP_SECTION_SPECS]
    section_map = {str(section.get("title", "")): str(section.get("summary", "")) for section in result.sections}
    method_text = section_map.get(str(DEEP_SECTION_SPECS[1]["title"]), "")
    result_text = section_map.get(str(DEEP_SECTION_SPECS[2]["title"]), "")
    reproduction_text = section_map.get(str(DEEP_SECTION_SPECS[3]["title"]), "") + "\n" + result.reproduction_notes
    forbidden_hits = [term for term in FORBIDDEN_QUALITY_TERMS if term in all_text.lower()]

    dimensions = {
        "total_length": _bounded_score(total_length, [(1200, 6), (2200, 12), (3600, 18)]),
        "four_sections_complete": _four_sections_score(result.sections, expected_titles),
        "chinese_ratio": _chinese_ratio_score(stripped),
        "method_detail": _keyword_detail_score(
            method_text,
            ["\u65b9\u6cd5", "\u6a21\u578b", "\u7b97\u6cd5", "\u635f\u5931", "\u516c\u5f0f", "\u7ea6\u675f", "\u8bad\u7ec3", "\u63a8\u7406", "\u6d41\u7a0b", "\u8fb9\u754c", "loss", "equation", "algorithm"],
            max_points=16,
        ),
        "result_evidence": _result_evidence_score(result_text, result.sections),
        "reproduction_advice": _keyword_detail_score(
            reproduction_text,
            ["\u590d\u73b0", "\u6570\u636e", "\u914d\u7f6e", "\u6307\u6807", "\u57fa\u7ebf", "\u6d88\u878d", "\u968f\u673a", "\u79cd\u5b50", "\u9884\u7b97", "\u98ce\u9669", "\u6838\u5bf9", "scripts", "configs"],
            max_points=14,
        ),
        "forbidden_terms": max(0, 8 - 2 * len(forbidden_hits)),
    }
    score = int(sum(int(value) for value in dimensions.values()))
    if provider_mode != "llm":
        score = min(score, 68)
    needs_review = bool(score < 70 or forbidden_hits or llm_error)
    return {
        "score": score,
        "needs_review": needs_review,
        "provider_mode": provider_mode,
        "llm_error": llm_error,
        "dimensions": dimensions,
        "total_length": total_length,
        "chinese_ratio": round(_chinese_ratio(stripped), 3),
        "forbidden_terms": forbidden_hits,
    }


def _score_section(section: dict[str, object]) -> dict[str, object]:
    summary = str(section.get("summary", ""))
    evidence = section.get("evidence")
    length_points = _bounded_score(len(_strip_markdown(summary)), [(300, 20), (650, 35), (1000, 45)])
    chinese_points = min(25, int(_chinese_ratio(summary) * 60))
    evidence_points = 20 if isinstance(evidence, list) and len(evidence) >= 2 else 10 if evidence else 0
    detail_points = 10 if any(token in summary for token in ("公式", "流程", "指标", "实验", "复现", "数据", "损失", "约束")) else 0
    score = min(100, length_points + chinese_points + evidence_points + detail_points)
    return {
        "score": score,
        "needs_review": score < 70 or section.get("confidence") == "needs_review",
        "length": len(_strip_markdown(summary)),
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
    }


def _bounded_score(value: int, thresholds: list[tuple[int, int]]) -> int:
    score = 0
    for threshold, points in thresholds:
        if value >= threshold:
            score = points
    return score


def _four_sections_score(sections: list[dict[str, object]], expected_titles: list[str]) -> int:
    section_map = {str(section.get("title", "")): str(section.get("summary", "")) for section in sections}
    points = 0
    for title in expected_titles:
        body = section_map.get(title, "")
        if len(_strip_markdown(body)) >= 240:
            points += 4
        elif body.strip():
            points += 2
    return min(16, points)


def _chinese_ratio_score(text: str) -> int:
    ratio = _chinese_ratio(text)
    if ratio >= 0.35:
        return 14
    if ratio >= 0.22:
        return 9
    if ratio >= 0.1:
        return 5
    return 0


def _chinese_ratio(text: str) -> float:
    meaningful = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text)
    if not meaningful:
        return 0.0
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    return len(chinese) / len(meaningful)


def _keyword_detail_score(text: str, keywords: list[str], *, max_points: int) -> int:
    if not text.strip():
        return 0
    lowered = text.lower()
    hits = sum(1 for keyword in keywords if keyword.lower() in lowered)
    length_bonus = 1 if len(_strip_markdown(text)) >= 600 else 0
    return min(max_points, hits * 2 + length_bonus * 4)


def _result_evidence_score(result_text: str, sections: list[dict[str, object]]) -> int:
    score = _keyword_detail_score(
        result_text,
        ["\u5b9e\u9a8c", "\u7ed3\u679c", "\u6307\u6807", "\u8bef\u5dee", "\u57fa\u7ebf", "\u6570\u636e", "\u8868", "\u56fe", "\u6d88\u878d", "benchmark", "metric", "error"],
        max_points=10,
    )
    has_number = bool(re.search(r"\d", result_text))
    score += 2 if has_number else 0
    result_section = next((section for section in sections if section.get("title") == str(DEEP_SECTION_SPECS[2]["title"])), {})
    evidence = result_section.get("evidence")
    if isinstance(evidence, list) and evidence:
        score += 2
    return min(14, score)
