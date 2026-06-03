from __future__ import annotations

from apps.assistant.models import AssistantExchange, AssistantSession


def create_assistant_exchange(session: AssistantSession, question: str) -> AssistantExchange:
    sources = _sources_from_scope(session.scope_json)
    context_warning = "" if sources else "当前会话没有限定到具体来源，回答仅记录问题并提示补充范围。"
    if sources:
        source_labels = ", ".join(source["label"] for source in sources[:5])
        answer = (
            "已收到问题。第一版研究助理会严格限定在会话 scope 内组织回答；"
            f"本次可用来源包括：{source_labels}。"
        )
    else:
        answer = "请先在会话 scope 中限定论文、文档、实验或知识空间范围，再进行可靠问答。"
    return AssistantExchange.objects.create(
        session=session,
        question=question,
        answer=answer,
        sources=sources,
        model="scoped_stub_v1",
        usage={"prompt_chars": len(question), "completion_chars": len(answer)},
        context_warning=context_warning,
    )


def _sources_from_scope(scope: dict) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    for key, label in [
        ("paper_ids", "paper"),
        ("document_ids", "document"),
        ("experiment_ids", "experiment"),
        ("space_ids", "space"),
    ]:
        for object_id in scope.get(key, []) or []:
            sources.append({"type": label, "id": object_id, "label": f"{label}:{object_id}"})
    return sources
