from __future__ import annotations

import json
import re
from dataclasses import dataclass

from django.db import transaction
from pypdf import PdfReader

from apps.ai.minimax import MiniMaxAPIError, MiniMaxConfigError, call_minimax_chat
from apps.library.keywords import canonical_keyword_names, get_or_create_canonical_keyword
from apps.papers.metadata import (
    DEFAULT_UPLOAD_TITLE,
    clean_author_candidate,
    extract_arxiv,
    extract_authors_from_text,
    extract_doi,
    extract_pdf_metadata,
    extract_text,
    extract_year,
    source_url_for,
    split_authors,
    title_from_filename,
)
from apps.papers.models import Paper, PaperDeepProfile, PaperLightProfile
from apps.storage.provider import get_storage_provider
from apps.tasks.models import TaskRecord
from apps.tasks.sanitization import sanitize_task_error

DOMAIN_KEYWORDS = [
    "PINN",
    "Physics-Informed Neural Network",
    "Transformer",
    "Neural Operator",
    "DeepONet",
    "FNO",
    "PDE",
    "Navier-Stokes",
    "inverse problem",
    "operator learning",
    "finite element",
    "spectral method",
    "diffusion",
    "Burgers",
    "Darcy",
]

SKIM_MARKDOWN_TITLES = ("研究背景", "方法原理", "主要结果", "关键词")
SKIM_FIELD_TITLES = {
    "background": "研究背景",
    "method": "方法原理",
    "results": "主要结果",
}
LIGHT_TASK_TYPES = ("paper_light_process", "paper_ai_light_process")


@dataclass(frozen=True)
class LightProcessResult:
    paper: Paper
    profile: PaperLightProfile
    task: TaskRecord


def run_light_processing(paper: Paper) -> LightProcessResult:
    return run_light_processing_with_options(paper, use_ai=False)


def run_light_processing_with_options(paper: Paper, *, use_ai: bool = False) -> LightProcessResult:
    task = TaskRecord.objects.create(
        task_type="paper_ai_light_process" if use_ai else "paper_light_process",
        status=TaskRecord.Status.RUNNING,
        progress=10,
        stage="reading_pdf",
        object_type="paper",
        object_id=paper.id,
    )
    return run_light_processing_with_task(paper, task=task, use_ai=use_ai)


def enqueue_light_processing(paper: Paper, *, use_ai: bool = False) -> TaskRecord:
    task_type = "paper_ai_light_process" if use_ai else "paper_light_process"
    original_status = paper.status
    with transaction.atomic():
        locked_paper = Paper.objects.select_for_update().get(pk=paper.pk)
        original_status = locked_paper.status
        active_task = (
            TaskRecord.objects.filter(
                object_type="paper",
                object_id=locked_paper.id,
                task_type__in=LIGHT_TASK_TYPES,
                status__in=[TaskRecord.Status.PENDING, TaskRecord.Status.RUNNING],
            )
            .order_by("-updated_at", "-id")
            .first()
        )
        if active_task:
            return active_task

        task = TaskRecord.objects.create(
            task_type=task_type,
            status=TaskRecord.Status.PENDING,
            progress=0,
            stage="queued",
            object_type="paper",
            object_id=locked_paper.id,
            result={"original_paper_status": original_status},
        )
        if locked_paper.status not in {Paper.Status.LIGHT_READY, Paper.Status.DEEP_READY}:
            locked_paper.status = Paper.Status.LIGHT_PROCESSING
            locked_paper.save(update_fields=["status", "updated_at"])

    from apps.papers.tasks import run_paper_light_process_task

    run_paper_light_process_task.apply_async(
        args=[task.object_id, task.id, use_ai],
        queue="ai_q" if use_ai else "fast_q",
    )
    return task


def run_light_processing_with_task(paper: Paper, *, task: TaskRecord, use_ai: bool = False) -> LightProcessResult:
    task_result = _dict_result(task.result)
    if not task_result.get("original_paper_status"):
        task.result = {**task_result, "original_paper_status": paper.status}
        task.save(update_fields=["result", "updated_at"])
    try:
        result = _process(paper, task, use_ai=use_ai)
    except Exception as exc:
        restored_status, failure_result = _light_failure_fallback(paper, task, exc)
        task.status = TaskRecord.Status.FAILED
        task.error = sanitize_task_error(exc)
        task.progress = 100
        task.stage = "failed"
        task.result = {**_dict_result(task.result), **failure_result}
        task.save(update_fields=["status", "error", "progress", "stage", "result", "updated_at"])
        paper.status = restored_status
        paper.save(update_fields=["status", "updated_at"])
        raise
    return result


def _light_failure_fallback(paper: Paper, task: TaskRecord, exc: Exception) -> tuple[str, dict[str, object]]:
    active_deep_profile = PaperDeepProfile.objects.filter(paper=paper, is_active=True).first()
    active_light_profile = PaperLightProfile.objects.filter(paper=paper, is_active=True).first()
    restored_status = Paper.Status.NEEDS_REVIEW if paper.source_pdf_path else Paper.Status.FAILED
    task_result = _dict_result(task.result)
    result: dict[str, object] = {
        "paper_id": paper.id,
        "original_paper_status": task_result.get("original_paper_status", paper.status),
        "error": sanitize_task_error(exc),
    }
    if active_deep_profile:
        restored_status = Paper.Status.DEEP_READY
        result["active_deep_profile_id"] = active_deep_profile.id
    elif active_light_profile:
        restored_status = Paper.Status.LIGHT_READY
        result["active_light_profile_id"] = active_light_profile.id
    result["restored_paper_status"] = restored_status
    return restored_status, result


def _process(paper: Paper, task: TaskRecord, *, use_ai: bool) -> LightProcessResult:
    if not paper.source_pdf_path:
        raise ValueError("paper has no uploaded PDF")

    task.status = TaskRecord.Status.RUNNING
    task.progress = 10
    task.stage = "reading_pdf"
    task.save(update_fields=["status", "progress", "stage", "updated_at"])

    paper.status = Paper.Status.LIGHT_PROCESSING
    paper.save(update_fields=["status", "updated_at"])

    path = get_storage_provider().resolve(paper.source_pdf_path)
    data = path.read_bytes()
    extracted = extract_pdf_metadata(data, filename=path.name)
    text = extracted.text
    extracted_title = extracted.title
    authors = extracted.authors or []
    year = extracted.year
    doi = extracted.doi
    arxiv_id = extracted.arxiv_id
    source_url = extracted.source_url
    abstract = extracted.abstract
    keywords = _extract_keywords(f"{paper.title}\n{text}")
    ai_profile = None
    ai_error = ""
    if use_ai:
        task.stage = "ai_light_profile"
        task.progress = 45
        task.save(update_fields=["stage", "progress", "updated_at"])
        try:
            ai_profile = _generate_ai_light_profile(paper, text, keywords)
            keywords = canonical_keyword_names([*keywords, *ai_profile["keywords"]])[:12]
        except (MiniMaxAPIError, MiniMaxConfigError) as exc:
            ai_error = sanitize_task_error(exc)

    with transaction.atomic():
        if _should_backfill_title_from_pdf(paper.title, extracted_title):
            paper.title = extracted_title[:500]
        if authors and not paper.authors:
            paper.authors = authors
        if year and not paper.year:
            paper.year = year
        if doi and not paper.doi:
            paper.doi = doi[:160]
        if arxiv_id and not paper.arxiv_id:
            paper.arxiv_id = arxiv_id[:80]
        if abstract and not paper.abstract:
            paper.abstract = abstract
        if source_url and not paper.source_url:
            paper.source_url = source_url[:500]
        paper.status = Paper.Status.LIGHT_READY
        paper.save()

        existing_keywords = list(paper.keywords.values_list("name", flat=True))
        keywords = canonical_keyword_names([*existing_keywords, *keywords])[:12]
        keyword_objects = [get_or_create_canonical_keyword(item) for item in keywords]
        paper.keywords.set(keyword_objects)

        PaperLightProfile.objects.filter(paper=paper, is_active=True).update(is_active=False)
        version = (PaperLightProfile.objects.filter(paper=paper).count() or 0) + 1
        profile = PaperLightProfile.objects.create(
            paper=paper,
            version=version,
            is_active=True,
            generator="minimax_m27_light_v1" if ai_profile else "rule_based_v1",
            keywords=keywords,
            background=ai_profile["background"] if ai_profile else _background_summary(paper, keywords),
            method=ai_profile["method"] if ai_profile else _method_summary(text),
            results=ai_profile["results"] if ai_profile else _results_summary(text),
            source_text_preview=text[:4000],
        )

        task.status = TaskRecord.Status.SUCCESS
        task.progress = 100
        task.stage = "light_ready"
        task.result = {"paper_id": paper.id, "profile_id": profile.id, "keywords": keywords}
        if ai_profile:
            task.result["model"] = ai_profile["model"]
            task.result["usage"] = ai_profile["usage"]
        if ai_error:
            task.result["ai_error"] = ai_error
        task.save(update_fields=["status", "progress", "stage", "result", "updated_at"])

    paper.refresh_from_db()
    return LightProcessResult(paper=paper, profile=profile, task=task)


def _extract_text(reader: PdfReader, max_pages: int = 8, max_chars: int = 24000) -> str:
    return extract_text(reader, max_pages=max_pages, max_chars=max_chars)


def _dict_result(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _generate_ai_light_profile(paper: Paper, text: str, keywords: list[str]) -> dict[str, object]:
    excerpt = text[:12000] if text else "PDF 文本暂未成功抽取，请仅根据题名和已有关键词给出保守概览。"
    response = call_minimax_chat(
        [
            {
                "role": "system",
                "content": (
                    "你是 AI for PDEs 团队 A510 知识库的论文粗读助手。请快速阅读论文文本，"
                    "生成足够详细的中文粗读概览。必须返回 Markdown 格式文本，不要返回 JSON。"
                    "Markdown 必须包含且只包含以下二级标题：## 研究背景、## 方法原理、## 主要结果、## 关键词。"
                    "研究背景、方法原理、主要结果每部分至少 2 段，每段至少 80 个中文字符；"
                    "可使用 Markdown 列表、加粗、行内公式 $...$ 和块公式 $$...$$。"
                    "研究背景要说明领域问题、现有方法痛点、本文目标和适合归入的知识类别。"
                    "方法原理要解释核心直觉、模型/算法流程、物理约束或实验设计思路。"
                    "主要结果要总结核心发现、量化/定性结论、适用边界和还需要深度处理核对的证据。"
                    "关键词部分用 Markdown 列表输出 3 到 8 个规范英文关键词，不要输出中文关键词。"
                    "如果证据不足，也要写出保守判断和待核对事项，不得编造不存在的数字。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"题名：{paper.title}\n"
                    f"年份：{paper.year or '未知'}\n"
                    f"来源：{paper.venue or '未知'}\n"
                    f"已有关键词：{', '.join(keywords) if keywords else '无'}\n"
                    "可抽取文本：\n"
                    f"{excerpt}"
                ),
            },
        ],
        max_tokens=2200,
    )
    rendered = _parse_ai_profile_response(response.content, paper_title=paper.title)
    return {
        "keywords": canonical_keyword_names(rendered["keywords"]),
        "background": _clean_ai_field(rendered["background"], field_name="background", paper_title=paper.title),
        "method": _clean_ai_field(rendered["method"], field_name="method", paper_title=paper.title),
        "results": _clean_ai_field(rendered["results"], field_name="results", paper_title=paper.title),
        "model": response.model,
        "usage": response.usage,
    }


def _parse_ai_profile_response(content: str, *, paper_title: str) -> dict[str, object]:
    try:
        payload = _parse_ai_profile_json(content)
    except (json.JSONDecodeError, ValueError):
        return _parse_ai_profile_markdown(content, paper_title=paper_title)
    return _render_skim_payload(payload, paper_title=paper_title)


def _parse_ai_profile_markdown(content: str, *, paper_title: str) -> dict[str, object]:
    sections = _split_markdown_sections(content)
    if not _has_complete_skim_markdown_contract(sections):
        return _fallback_skim_profile(paper_title=paper_title)
    rendered = {
        "keywords": _keywords_from_markdown_section(sections.get("关键词", "")),
        "background": _format_light_section(
            "研究背景",
            _markdown_paragraphs(sections.get("研究背景", "")),
            paper_title=paper_title,
            field_name="background",
        ),
        "method": _format_light_section(
            "方法原理",
            _markdown_paragraphs(sections.get("方法原理", "")),
            paper_title=paper_title,
            field_name="method",
        ),
        "results": _format_light_section(
            "主要结果",
            _markdown_paragraphs(sections.get("主要结果", "")),
            paper_title=paper_title,
            field_name="results",
        ),
    }
    return _apply_light_profile_quality_gate(rendered, paper_title=paper_title)


def _split_markdown_sections(content: str) -> dict[str, str]:
    cleaned = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE | re.DOTALL)
    pattern = re.compile(r"(?im)^#{1,3}\s*(研究背景|方法原理|主要结果|关键词)\s*$")
    matches = list(pattern.finditer(cleaned))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        sections[match.group(1)] = cleaned[start:end].strip()
    if not sections:
        sections["研究背景"] = cleaned
    return sections


def _has_complete_skim_markdown_contract(sections: dict[str, str]) -> bool:
    return all(title in sections for title in SKIM_MARKDOWN_TITLES)


def _markdown_paragraphs(markdown: str) -> list[str]:
    text = markdown.strip()
    if not text:
        return []
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    return [_strip_section_heading(block) for block in blocks if _strip_section_heading(block)]


def _keywords_from_markdown_section(markdown: str) -> list[str]:
    keywords = []
    for line in markdown.splitlines():
        item = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if item:
            keywords.extend(splitKeywordsLike(item))
    return keywords


def splitKeywordsLike(value: str) -> list[str]:
    return [item.strip(" `*：:;；，,") for item in re.split(r"[,，;；、\n]+", value) if item.strip(" `*：:;；，,")]


def _strip_section_heading(value: str) -> str:
    cleaned = re.sub(r"^\s*#{1,6}\s+.+$", "", value, count=1, flags=re.MULTILINE).strip()
    return re.sub(r"^\s*(研究背景|方法原理|主要结果)\s*$", "", cleaned, count=1, flags=re.MULTILINE).strip()


def _parse_ai_profile_json(content: str) -> dict[str, object]:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            cleaned = match.group(0)
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("MiniMax light profile response is not a JSON object")
    return payload


def _render_skim_payload(payload: dict[str, object], *, paper_title: str) -> dict[str, object]:
    if _has_structured_skim_schema(payload):
        return _render_structured_skim_payload(payload, paper_title=paper_title)
    return _render_legacy_ai_payload(payload, paper_title=paper_title)


def _has_structured_skim_schema(payload: dict[str, object]) -> bool:
    return any(
        key in payload
        for key in (
            "research_background",
            "method_principle",
            "main_results",
            "paper_type",
            "research_problem",
            "objective",
            "core_idea",
            "key_findings",
            "tldr",
            "taxonomy_hint",
            "evidence_level",
            "uncertainties",
        )
    )


def _render_structured_skim_payload(payload: dict[str, object], *, paper_title: str) -> dict[str, object]:
    if any(key in payload for key in ("research_background", "method_principle", "main_results")):
        return _render_detailed_skim_payload(payload, paper_title=paper_title)

    taxonomy = payload.get("taxonomy_hint") if isinstance(payload.get("taxonomy_hint"), dict) else {}
    taxonomy_keywords = taxonomy.get("keywords", []) if isinstance(taxonomy, dict) else []
    primary_category = _text_value(taxonomy.get("primary_category")) if isinstance(taxonomy, dict) else ""
    key_findings = _as_text_list(payload.get("key_findings"))[:3]
    uncertainties = _as_text_list(payload.get("uncertainties"))[:3]

    paper_type = _paper_type_value(payload.get("paper_type"))
    research_problem = _text_value(payload.get("research_problem")) or "当前可抽取文本未明确说明核心痛点。"
    objective = _text_value(payload.get("objective")) or "当前可抽取文本未明确说明研究目标。"
    core_idea = _text_value(payload.get("core_idea")) or "当前可抽取文本未明确说明方法直觉。"
    tldr = _text_value(payload.get("tldr")) or f"{paper_title[:24]}速览"
    evidence_level = _evidence_level_value(payload.get("evidence_level"))
    category_text = primary_category or "待人工归类"
    findings_text = _join_items(key_findings) or "当前文本未提供可核验的主要结果。"
    uncertainty_text = _join_items(uncertainties) or "暂未识别到明确不确定项。"
    keywords = [*taxonomy_keywords, *_as_text_list(payload.get("keywords"))]

    return {
        "keywords": canonical_keyword_names(keywords),
        "background": (
            _format_light_section(
                "研究背景",
                [
                    f"论文类型可暂定为 {paper_type}。这篇论文的核心痛点是：{research_problem}。作者希望推进的研究目标是：{objective}。",
                    f"粗读结论可以概括为：{tldr}。从知识库归类看，它建议放入“{category_text}”或相邻方向；当前证据等级为 {evidence_level}，后续仍需要结合原文进一步核对。",
                ],
                paper_title=paper_title,
                field_name="background",
            )
        ),
        "method": (
            _format_light_section(
                "方法原理",
                [
                    f"方法原理的核心直觉是：{core_idea}。这部分用于解释论文如何跨越前述痛点，而不是只复述题名或关键词。",
                    "粗读阶段会保留模型结构、训练目标、物理约束、实验协议和实现细节的待核对入口；真正的公式、算法流程和工程细节仍应在深度处理中逐项验证。",
                ],
                paper_title=paper_title,
                field_name="method",
            )
        ),
        "results": (
            _format_light_section(
                "主要结果",
                [
                    f"主要结果包括：{findings_text}。这些发现应优先被看作粗读索引，用于判断论文是否值得进一步精读和复现。",
                    f"仍需核对的不确定项包括：{uncertainty_text}。后续深度处理需要回到原文检查数字、基线、误差指标、消融结论、复杂度和泛化场景，避免把短摘要误当成完整证据。",
                ],
                paper_title=paper_title,
                field_name="results",
            )
        ),
    }


def _render_detailed_skim_payload(payload: dict[str, object], *, paper_title: str) -> dict[str, object]:
    rendered = {
        "keywords": canonical_keyword_names(_as_text_list(payload.get("keywords"))),
        "background": _format_light_section(
            "研究背景",
            _as_text_list(payload.get("research_background")),
            paper_title=paper_title,
            field_name="background",
        ),
        "method": _format_light_section(
            "方法原理",
            _as_text_list(payload.get("method_principle")),
            paper_title=paper_title,
            field_name="method",
        ),
        "results": _format_light_section(
            "主要结果",
            _as_text_list(payload.get("main_results")),
            paper_title=paper_title,
            field_name="results",
        ),
    }
    return _apply_light_profile_quality_gate(rendered, paper_title=paper_title)


def _apply_light_profile_quality_gate(rendered: dict[str, object], *, paper_title: str) -> dict[str, object]:
    return {
        "keywords": rendered.get("keywords", []),
        "background": _clean_ai_field(
            rendered.get("background", ""), field_name="background", paper_title=paper_title
        ),
        "method": _clean_ai_field(rendered.get("method", ""), field_name="method", paper_title=paper_title),
        "results": _clean_ai_field(
            rendered.get("results", ""), field_name="results", paper_title=paper_title
        ),
    }


def _render_legacy_ai_payload(payload: dict[str, object], *, paper_title: str) -> dict[str, object]:
    background = _text_value(payload.get("background"))
    method = _text_value(payload.get("method"))
    results = _text_value(payload.get("results"))
    return {
        "keywords": _as_text_list(payload.get("keywords")),
        "background": (
            (
                f"{background} "
                if background and _passes_light_profile_quality(background, field_name="background")
                else ""
            )
        )
        + (
            f"论文类型：Other。核心痛点：旧版 AI JSON 未提供独立痛点字段，当前只能根据《{paper_title}》"
            "和可抽取文本保守判断。研究目标：先形成可检索、可筛选的入库概览。"
            "一句话速览：旧版粗读结果需复核。建议分类：待人工归类；证据等级：weak。"
        ),
        "method": (
            f"{method} " if method and _passes_light_profile_quality(method, field_name="method") else ""
        )
        + (
            "方法直觉：旧版 AI JSON 未提供结构化方法直觉，系统只保留可读线索用于粗读筛选。"
            "这不替代后续对公式、算法流程、实现细节和实验协议的精读核对。"
        ),
        "results": (
            f"{results} " if results and _passes_light_profile_quality(results, field_name="results") else ""
        )
        + (
            "主要结果：旧版 AI JSON 未提供结构化 key_findings，当前不能把短句当作完整结论。"
            "不确定项：需要核对原文中的实验数字、基线、误差指标和消融结论。"
            "需要深度处理核对的事项：回到原文检查证据来源，避免补造量化结果。"
        ),
    }


def _as_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [_text_value(item) for item in value if _text_value(item)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _text_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _format_light_section(title: str, paragraphs: list[str], *, paper_title: str, field_name: str) -> str:
    cleaned = [_normalize_light_paragraph(paragraph) for paragraph in paragraphs if paragraph.strip()]
    while len(cleaned) < 2:
        cleaned.append(_ai_field_fallback_paragraph(field_name=field_name, paper_title=paper_title, index=len(cleaned)))
    expanded = [
        paragraph
        if len(paragraph) >= 80 and paragraph.count("。") >= 1
        else f"{paragraph} 这段内容用于粗读筛选，需要保留足够上下文，帮助研究者判断论文是否值得进入后续精读和知识体系归类。"
        for paragraph in cleaned[:4]
    ]
    while len("\n\n".join(expanded)) < 240 and len(expanded) < 4:
        expanded.append(
            _ai_field_fallback_paragraph(field_name=field_name, paper_title=paper_title, index=len(expanded))
        )
    return "\n\n".join(expanded)


def _normalize_light_paragraph(paragraph: str) -> str:
    cleaned = paragraph.strip()
    if "\n" in cleaned or cleaned.startswith(("- ", "* ", "$$")):
        return cleaned
    return cleaned.rstrip("。") + "。"


def _paper_type_value(value: object) -> str:
    allowed = {"Algorithm", "Theory", "Survey", "System", "Application", "Benchmark", "Dataset", "Other"}
    cleaned = _text_value(value)
    return cleaned if cleaned in allowed else "Other"


def _evidence_level_value(value: object) -> str:
    cleaned = _text_value(value).lower()
    return cleaned if cleaned in {"strong", "medium", "weak"} else "medium"


def _join_items(items: list[str]) -> str:
    normalized = [item.rstrip("。；; ") for item in items if item.strip()]
    return "；".join(normalized)


def _clean_ai_field(value: object, *, field_name: str = "overview", paper_title: str = "") -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [re.sub(r"[ \t]+", " ", paragraph).strip() for paragraph in re.split(r"\n{2,}", raw)]
    cleaned = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    if _passes_light_profile_quality(cleaned, field_name=field_name):
        return cleaned
    return _ai_field_fallback(field_name=field_name, paper_title=paper_title)


def _passes_light_profile_quality(value: str, *, field_name: str = "overview") -> bool:
    sentence_count = sum(value.count(mark) for mark in ("。", ".", "！", "!", "？", "?"))
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", value) if paragraph.strip()]
    chinese_chars = _count_chinese_chars(value)
    letter_chars = sum(1 for char in value if char.isascii() and char.isalpha())
    title = SKIM_FIELD_TITLES.get(field_name)
    has_duplicate_title = bool(title and re.search(rf"(?m)^\s*#{{0,6}}\s*{re.escape(title)}\s*$", value))
    return (
        len(value) >= 120
        and sentence_count >= 2
        and len(paragraphs) >= 2
        and chinese_chars >= 80
        and chinese_chars >= letter_chars
        and not has_duplicate_title
    )


def _count_chinese_chars(value: str) -> int:
    return sum("\u4e00" <= char <= "\u9fff" for char in value)


def _fallback_skim_profile(*, paper_title: str) -> dict[str, object]:
    return {
        "keywords": [],
        "background": _ai_field_fallback(field_name="background", paper_title=paper_title),
        "method": _ai_field_fallback(field_name="method", paper_title=paper_title),
        "results": _ai_field_fallback(field_name="results", paper_title=paper_title),
    }


def _ai_field_fallback(*, field_name: str, paper_title: str) -> str:
    title = paper_title or "该论文"
    templates = {
        "background": (
            _format_light_section(
                "研究背景",
                [
                    f"围绕《{title}》，当前粗读只能从题名、可抽取文本和关键词判断研究背景。系统会把它先作为待核对论文纳入索引，重点观察它是否与 PDE 建模、科学机器学习、数值求解或相关应用问题有关。",
                    "由于原文证据不足，暂时不能可靠判断它的完整问题设定、已有方法痛点和知识体系归属。后续应通过 AI 粗读重试或深度处理补充引言、相关工作和任务定义，再决定是否进入核心文献库。",
                ],
                paper_title=title,
                field_name="background",
            )
        ),
        "method": (
            _format_light_section(
                "方法原理",
                [
                    f"围绕《{title}》，当前文本尚不足以可靠还原完整方法原理。系统只保留可读的保守说明，提醒后续重点核对模型结构、训练目标、物理约束、边界条件和实验协议。",
                    "这部分内容用于入库预览和粗读筛选，不替代人工精读或深度处理结论。真正可复用的方法知识需要从公式、算法流程、图表说明和实验设置中继续抽取。",
                ],
                paper_title=title,
                field_name="method",
            )
        ),
        "results": (
            _format_light_section(
                "主要结果",
                [
                    f"围绕《{title}》，当前粗读未获得足够可核验的实验或理论结论，因此不能把短输出当成完整论文贡献。系统会保留待核对状态，避免补造不存在的性能数字或理论边界。",
                    "后续需要检查误差、基线、消融、复杂度、泛化场景和失败案例。深度处理应回到原文确认所有数字、结论和图表证据，再决定是否写入知识体系或复现计划。",
                ],
                paper_title=title,
                field_name="results",
            )
        ),
    }
    return templates.get(
        field_name,
        (
            f"关于《{title}》的 {field_name} 信息当前较少。"
            "系统使用稳定的多句中文概览，保留论文入库时的基本可读性。"
            "后续可以通过 AI 粗读或深度处理补全更可靠的学术细节。"
        ),
    )


def _ai_field_fallback_paragraph(*, field_name: str, paper_title: str, index: int) -> str:
    title = paper_title or "该论文"
    paragraphs = {
        "background": [
            f"围绕《{title}》，当前证据不足以完整还原研究背景。系统会先记录题名、关键词和可抽取文本中的主题线索，帮助后续判断它与 PDE、科学机器学习或相关数值问题的关系。",
            "后续需要回到引言和相关工作部分，确认作者声称的核心痛点、已有方法缺口、研究目标和知识类别。证据不足时应保持保守，不把自动生成内容当作定论。",
        ],
        "method": [
            f"围绕《{title}》，当前证据不足以完整还原方法原理。系统会先记录可能涉及的模型结构、训练目标、物理约束、边界条件和实验协议，作为后续精读入口。",
            "后续需要从公式、算法流程、伪代码、图表和实现说明中核对真正的方法贡献。粗读内容只用于筛选，不替代严谨的技术解构。",
        ],
        "results": [
            f"围绕《{title}》，当前证据不足以可靠总结主要结果。系统不会补造误差、排名、复杂度或理论结论，而是把需要核对的实验和证明线索保留下来。",
            "后续需要检查数据集、基线、指标、消融、泛化场景和失败案例。只有原文能支持的数字和结论才应进入最终知识库摘要。",
        ],
    }
    options = paragraphs.get(field_name, paragraphs["background"])
    return options[index % len(options)]


def _clean_metadata_value(value: object) -> str:
    return str(value or "").strip()


def _split_authors(value: str) -> list[str]:
    return split_authors(value)


def _extract_authors_from_text(text: str, title: str) -> list[str]:
    return extract_authors_from_text(text, title)


def _clean_author_candidate(value: str) -> str:
    return clean_author_candidate(value)


def _extract_year(text: str, metadata: object) -> int | None:
    return extract_year(text, metadata)


def _extract_doi(text: str) -> str:
    return extract_doi(text)


def _extract_arxiv(text: str) -> str:
    return extract_arxiv(text)


def _extract_keywords(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for keyword in DOMAIN_KEYWORDS:
        if keyword.lower() in lowered:
            found.append(keyword)
    return canonical_keyword_names(found)[:12]


def _looks_like_filename_title(title: str) -> bool:
    lowered = title.lower()
    return (
        bool(re.search(r"[_/\\]", title))
        or lowered in {DEFAULT_UPLOAD_TITLE.lower(), "untitled paper"}
        or bool(re.fullmatch(r"paper(?: upload)?(?:\s+[\da-f.-]{4,})?", lowered))
        or any(token in lowered for token in ["arxiv", "download", ".pdf"])
    )


def _should_backfill_title_from_pdf(current_title: str, extracted_title: str) -> bool:
    return _looks_like_filename_title(current_title) and _is_reliable_extracted_title(extracted_title)


def _is_reliable_extracted_title(title: str) -> bool:
    value = str(title or "").strip()
    if len(value) < 8:
        return False
    lowered = value.lower()
    if lowered in {DEFAULT_UPLOAD_TITLE.lower(), "untitled paper"}:
        return False
    if re.search(r"^(?:published as|accepted as|accepted at|under review|conference paper|proceedings of)\b", value, re.IGNORECASE):
        return False
    if re.search(r"\b(?:@|\.edu\b|\.com\b|atlanta,\s*ga)\b", value, re.IGNORECASE):
        return False
    if re.search(r"\b(?:georgia institute|university|department|school|college|institute of technology)\b", value, re.IGNORECASE):
        return False
    if len(value) > 180 and sum(token in lowered for token in ("author", "abstract", "conference", "paper")) >= 2:
        return False
    broken_word_markers = len(re.findall(r"\b[A-Z]\s+[A-Z][A-Z]{2,}\b", value))
    spaced_hyphen_markers = len(re.findall(r"\b[A-Z]+(?:\s*-\s*[A-Z]+){1,}\b", value))
    if broken_word_markers >= 1 and spaced_hyphen_markers >= 1:
        return False
    return True


def _background_summary(paper: Paper, keywords: list[str]) -> str:
    topic = "、".join(keywords[:5]) if keywords else "偏微分方程和科学机器学习"
    return (
        f"论文类型：Other。核心痛点：当前规则扫描识别到的主题包括 {topic}，但尚未完成 AI 粗读。"
        "研究目标：先建立可检索的入库索引，帮助研究者判断是否需要进一步阅读。"
        "一句话速览：规则版保守概览。建议分类：待人工归类；证据等级：weak。"
    )


def _method_summary(text: str) -> str:
    sentence = _find_sentence(text, ["method", "propose", "model", "framework", "architecture"])
    if sentence:
        return (
            f"方法直觉：{sentence}。该线索来自 PDF 文本的规则匹配，仍需在深度处理中核对完整 pipeline。"
            "粗读筛选阶段不替代精读；后续需要检查损失函数、约束嵌入方式和实现细节。"
        )
    return _ai_field_fallback(field_name="method", paper_title="")


def _results_summary(text: str) -> str:
    sentence = _find_sentence(text, ["result", "experiment", "accuracy", "error", "benchmark"])
    if sentence:
        return (
            f"主要结果：{sentence}。该线索来自 PDF 文本的规则匹配，后续需要核对基线、指标、消融和泛化场景。"
            "如果原文没有明确数字或实验表格，系统不得补造量化结论；这些事项应在深度处理阶段复核。"
        )
    return _ai_field_fallback(field_name="results", paper_title="")


def _find_sentence(text: str, needles: list[str]) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        lowered = sentence.lower()
        if any(needle in lowered for needle in needles):
            return sentence[:500]
    return ""
