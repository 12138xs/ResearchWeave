from __future__ import annotations

from enum import StrEnum

from django.db import models


class SourceKind(models.TextChoices):
    UNCLASSIFIED = "unclassified", "未分类"
    PAPER_FULLTEXT = "paper_fulltext", "论文原文"
    PAPER_ABSTRACT = "paper_abstract", "论文摘要"
    HUMAN_RECORD = "human_record", "人工记录"
    DERIVED_RESEARCH_CARD = "derived_research_card", "衍生整理卡"
    AGENT_SUMMARY = "agent_summary", "Agent 摘要"
    EXPERIMENT_PLAN = "experiment_plan", "实验计划"
    EXPERIMENT_OBSERVATION = "experiment_observation", "实验观察"
    EXPERIMENT_INTERPRETATION = "experiment_interpretation", "实验解释"
    CODE_REFERENCE = "code_reference", "代码引用"


class SourceType(StrEnum):
    MATERIAL_EVIDENCE = "material_evidence"
    RESEARCH_CARD = "research_card"
    LEGACY_PAPER = "legacy_paper"
    EXPERIMENT_PROJECT = "experiment_project"
    EXPERIMENT_RUN = "experiment_run"
    PERSONAL_ENTRY = "personal_entry"
    RESEARCH_PUBLICATION = "research_publication"


IDENTITY_FIELDS = {
    SourceType.MATERIAL_EVIDENCE: ("material_id", "version_id", "evidence_id"),
    SourceType.RESEARCH_CARD: ("material_id", "version_id", "research_card_id"),
    SourceType.LEGACY_PAPER: ("paper_id",),
    SourceType.EXPERIMENT_PROJECT: ("experiment_project_id",),
    SourceType.EXPERIMENT_RUN: ("experiment_project_id", "experiment_run_id"),
    SourceType.PERSONAL_ENTRY: ("personal_entry_id",),
    SourceType.RESEARCH_PUBLICATION: ("research_publication_id",),
}


class SourceContractError(ValueError):
    pass


def source_reference(*, source_type: SourceType | str, source_kind: SourceKind | str,
                     display_name: str, **identity: int) -> dict[str, object]:
    try:
        resolved_type = SourceType(source_type)
    except ValueError as error:
        raise SourceContractError("unsupported source type") from error
    if source_kind not in SourceKind.values or source_kind == SourceKind.UNCLASSIFIED:
        raise SourceContractError("source kind must be explicitly classified")
    expected = IDENTITY_FIELDS[resolved_type]
    if set(identity) != set(expected):
        raise SourceContractError(f"{resolved_type.value} requires native identity fields: {', '.join(expected)}")
    if any(not isinstance(identity[field], int) or identity[field] < 1 for field in expected):
        raise SourceContractError("source identity values must be positive integers")
    name = str(display_name).strip()
    if not name:
        raise SourceContractError("display name is required")
    return {
        "source_type": resolved_type.value,
        "source_kind": str(source_kind),
        "display_name": name,
        "identity": {field: identity[field] for field in expected},
    }


def material_evidence_reference(evidence) -> dict[str, object]:
    material = evidence.version.material
    return source_reference(
        source_type=SourceType.MATERIAL_EVIDENCE,
        source_kind=material.source_kind,
        display_name=material.title,
        material_id=material.pk,
        version_id=evidence.version_id,
        evidence_id=evidence.pk,
    )

