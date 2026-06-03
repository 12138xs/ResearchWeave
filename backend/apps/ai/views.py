from __future__ import annotations

from dataclasses import dataclass
from math import ceil
import re

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai.minimax import MiniMaxAPIError, MiniMaxConfigError, call_minimax_chat
from apps.ai.models import PaperQAExchange
from apps.ai.serializers import PaperQAExchangeSerializer
from apps.library.keywords import canonical_keyword_names
from apps.papers.models import Paper, PaperLightProfile


class PaperQARequestSerializer(serializers.Serializer):
    paper_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=20,
    )
    question = serializers.CharField(max_length=1200, trim_whitespace=True)
    mode = serializers.ChoiceField(choices=["compressed", "preview"], default="compressed")


@dataclass(frozen=True)
class PaperContext:
    paper: Paper
    profile: PaperLightProfile | None
    text: str
    used_sections: list[str]


class PaperQAView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PaperQARequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paper_ids = serializer.validated_data["paper_ids"]
        question = serializer.validated_data["question"]
        mode = serializer.validated_data["mode"]

        papers = list(
            Paper.objects.filter(id__in=paper_ids)
            .select_related("space")
            .prefetch_related("keywords", "light_profiles")
        )
        papers.sort(key=lambda paper: paper_ids.index(paper.id))
        if len(papers) != len(set(paper_ids)):
            found_ids = {paper.id for paper in papers}
            missing = [paper_id for paper_id in paper_ids if paper_id not in found_ids]
            return Response({"paper_ids": [f"找不到论文：{missing}"]}, status=status.HTTP_400_BAD_REQUEST)

        return _answer_paper_question(papers=papers, question=question, mode=mode, scope="selected_papers")


class CurrentPaperQARequestSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1200, trim_whitespace=True)
    mode = serializers.ChoiceField(choices=["compressed", "preview"], default="compressed")


class CurrentPaperQAView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk: int):
        serializer = CurrentPaperQARequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paper = get_object_or_404(
            Paper.objects.select_related("space").prefetch_related("keywords", "light_profiles"),
            pk=pk,
        )
        response = _answer_paper_question(
            papers=[paper],
            question=serializer.validated_data["question"],
            mode=serializer.validated_data["mode"],
            scope="single_paper",
        )
        if response.status_code == 200:
            PaperQAExchange.objects.create(
                paper=paper,
                user=request.user if request.user.is_authenticated else None,
                question=serializer.validated_data["question"],
                answer=str(response.data.get("answer", "")),
                mode=str(response.data.get("mode", serializer.validated_data["mode"])),
                model=str(response.data.get("model", "")),
                usage=response.data.get("usage", {}) if isinstance(response.data.get("usage", {}), dict) else {},
                sources=response.data.get("sources", []) if isinstance(response.data.get("sources", []), list) else [],
                context_warning=str(response.data.get("context_warning", "")),
            )
        return response


class CurrentPaperQAHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        paper = get_object_or_404(Paper, pk=pk)
        exchanges = paper.qa_exchanges.select_related("user").all()[:50]
        return Response(
            {
                "count": paper.qa_exchanges.count(),
                "results": PaperQAExchangeSerializer(exchanges, many=True).data,
            }
        )


def _answer_paper_question(
    *, papers: list[Paper], question: str, mode: str, scope: str
) -> Response:
    requested_mode = mode
    warning = ""
    contexts = [_build_paper_context(paper, mode) for paper in papers]
    messages = _build_messages(question, contexts, mode)
    token_limit = int(getattr(settings, "MODEL_GATEWAY_CONTEXT_TOKEN_LIMIT", 24000))
    estimated_tokens = estimate_message_tokens(messages)
    if mode == "preview" and estimated_tokens > token_limit:
        mode = "compressed"
        contexts = [_build_paper_context(paper, mode) for paper in papers]
        messages = _build_messages(question, contexts, mode)
        estimated_tokens = estimate_message_tokens(messages)
        warning = "preview 上下文超过模型限制，已自动回退到 compressed 模式。"
    if estimated_tokens > token_limit:
        contexts = _truncate_contexts_to_budget(contexts, question, mode, token_limit)
        messages = _build_messages(question, contexts, mode)
        estimated_tokens = estimate_message_tokens(messages)
        warning = (
            f"{warning} compressed 上下文仍然较长，已按来源顺序截断尾部内容。"
        ).strip()
    try:
        ai_response = call_minimax_chat(messages)
    except MiniMaxConfigError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except MiniMaxAPIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(
        {
            "answer": ai_response.content,
            "model": ai_response.model,
            "usage": ai_response.usage,
            "mode": mode,
            "requested_mode": requested_mode,
            "scope": scope,
            "context_warning": warning,
            "estimated_context_tokens": estimated_tokens,
            "context_token_limit": token_limit,
            "sources": [_source_payload(context) for context in contexts],
        }
    )


def _build_paper_context(paper: Paper, mode: str) -> PaperContext:
    profile = paper.light_profiles.filter(is_active=True).first()
    keywords = canonical_keyword_names([keyword.name for keyword in paper.keywords.all()])
    blocks = [
        f"论文编号: {paper.id}",
        f"题名: {paper.title}",
        f"年份: {paper.year or '未知'}",
        f"来源: {paper.venue or '未知'}",
        f"方向: {paper.area or '未标注'}",
        f"关键词: {', '.join(keywords) if keywords else '未提取'}",
    ]
    used_sections = ["题录", "关键词"]
    if paper.abstract:
        blocks.append(f"摘要: {_clip(paper.abstract, 1200)}")
        used_sections.append("摘要")
    if profile:
        if profile.background:
            blocks.append(f"背景: {_clip(profile.background, 900)}")
            used_sections.append("轻处理-背景")
        if profile.method:
            blocks.append(f"方法: {_clip(profile.method, 900)}")
            used_sections.append("轻处理-方法")
        if profile.results:
            blocks.append(f"结果: {_clip(profile.results, 900)}")
            used_sections.append("轻处理-结果")
        if mode == "preview" and profile.source_text_preview:
            blocks.append(f"原文预览: {_clip(profile.source_text_preview, 1400)}")
            used_sections.append("原文预览")
    return PaperContext(paper=paper, profile=profile, text="\n".join(blocks), used_sections=used_sections)


def _build_messages(question: str, contexts: list[PaperContext], mode: str) -> list[dict[str, str]]:
    context_text = "\n\n---\n\n".join(context.text for context in contexts)
    return [
        {
            "role": "system",
            "content": (
                "你是 AI for PDEs 团队知识库的学术问答助手。"
                "只能根据用户勾选论文的上下文回答，不要扩展到全库。"
                "回答使用自然、地道的中文。"
                "如果材料不足，直接说明不足，并指出还需要深度解析或原文段落。"
                "回答末尾用“来源范围：”列出使用的论文编号和标题。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"问题：{question}\n"
                f"上下文模式：{mode}\n"
                "以下是被勾选论文的压缩上下文：\n\n"
                f"{context_text}"
            ),
        },
    ]


def _source_payload(context: PaperContext) -> dict[str, object]:
    paper = context.paper
    keywords = canonical_keyword_names([keyword.name for keyword in paper.keywords.all()])
    return {
        "id": paper.id,
        "title": paper.title,
        "year": paper.year,
        "venue": paper.venue,
        "keywords": keywords,
        "used_sections": context.used_sections,
        "profile_version": context.profile.version if context.profile else None,
    }


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def estimate_message_tokens(messages: list[dict[str, str]]) -> int:
    estimate = 0.0
    for message in messages:
        content = str(message.get("content", ""))
        cjk_chars = len(re.findall(r"[\u3400-\u9fff]", content))
        other_chars = max(0, len(content) - cjk_chars)
        estimate += cjk_chars + ceil(other_chars / 3) + 8
    return max(1, ceil(estimate * 1.15))


def _truncate_contexts_to_budget(
    contexts: list[PaperContext], question: str, mode: str, token_limit: int
) -> list[PaperContext]:
    fixed_messages = _build_messages(question, [], mode)
    fixed_tokens = estimate_message_tokens(fixed_messages)
    budget_chars = max(200, (token_limit - fixed_tokens) * 2)
    per_context_chars = max(120, budget_chars // max(1, len(contexts)))
    truncated: list[PaperContext] = []
    for context in contexts:
        text = context.text
        used_sections = list(context.used_sections)
        if len(text) > per_context_chars:
            text = f"{text[:per_context_chars].rstrip()}\n[上下文已截断]"
            used_sections.append("上下文已截断")
        truncated.append(
            PaperContext(
                paper=context.paper,
                profile=context.profile,
                text=text,
                used_sections=used_sections,
            )
        )
    return truncated
