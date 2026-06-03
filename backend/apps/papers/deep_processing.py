from __future__ import annotations

import json
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max

from apps.annotations.validation import validate_annotation_anchors
from apps.papers.deep_parser import DeepParserInput, get_deep_parser_provider
from apps.papers.models import Paper, PaperDeepProfile
from apps.tasks.models import TaskRecord
from apps.tasks.sanitization import sanitize_task_error


DEEP_TASK_TYPE = "deep_process_paper"
PROCESSABLE_STATUSES = {Paper.Status.LIGHT_READY, Paper.Status.DEEP_READY, Paper.Status.NEEDS_REVIEW}
DEEP_SECTION_TITLES = ["引言与研究背景", "方法介绍", "核心结果与结论", "总结"]
FORBIDDEN_DEEP_OUTPUT_PATTERNS = (
    "source_pdf_path",
    "quarantine/uploads/",
    "/storage/",
    "\\storage\\",
    "storage root",
    "uploaded file",
    "upload path",
    "parser internals",
    "provider planning",
    "chain-of-thought",
    "now i need",
    "i need to ensure",
    "the instruction says",
)


class DeepProcessingUnavailable(ValueError):
    pass


class DeepTaskPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeepProcessResult:
    paper: Paper
    profile: PaperDeepProfile
    task: TaskRecord


def enqueue_deep_processing(paper: Paper, *, guidance: str = "") -> TaskRecord:
    original_status = paper.status
    with transaction.atomic():
        locked_paper = Paper.objects.select_for_update().get(pk=paper.pk)
        original_status = locked_paper.status
        active_task = (
            TaskRecord.objects.filter(
                object_type="paper",
                object_id=locked_paper.id,
                task_type=DEEP_TASK_TYPE,
                status__in=[TaskRecord.Status.PENDING, TaskRecord.Status.RUNNING],
            )
            .order_by("-updated_at", "-id")
            .first()
        )
        if active_task:
            return active_task

        _ensure_deep_processable(locked_paper)
        task = TaskRecord.objects.create(
            task_type=DEEP_TASK_TYPE,
            status=TaskRecord.Status.PENDING,
            progress=0,
            stage="queued",
            object_type="paper",
            object_id=locked_paper.id,
            result={
                "original_paper_status": original_status,
                "guidance": _clean_guidance(guidance),
            },
        )
        locked_paper.status = Paper.Status.DEEP_PROCESSING
        locked_paper.save(update_fields=["status", "updated_at"])

    from apps.papers.tasks import run_paper_deep_process_task

    try:
        run_paper_deep_process_task.apply_async(args=[task.object_id, task.id], queue="heavy_q")
    except Exception as exc:
        with transaction.atomic():
            locked_task = TaskRecord.objects.select_for_update().get(pk=task.pk)
            locked_paper = Paper.objects.select_for_update().get(pk=task.object_id)
            locked_task.status = TaskRecord.Status.FAILED
            locked_task.progress = 100
            locked_task.stage = "publish_failed"
            locked_task.error = "Unable to publish deep processing task."
            locked_task.result = {
                **_dict_result(locked_task.result),
                "paper_id": locked_paper.id,
                "restored_paper_status": original_status,
                "error": sanitize_task_error(exc),
            }
            locked_task.save(update_fields=["status", "progress", "stage", "error", "result", "updated_at"])
            locked_paper.status = original_status
            locked_paper.save(update_fields=["status", "updated_at"])
        raise DeepTaskPublishError("Unable to publish deep processing task.") from exc
    return task


def run_deep_processing_with_task(paper: Paper, *, task: TaskRecord) -> DeepProcessResult:
    try:
        return _process_deep_profile(paper, task)
    except Exception as exc:
        restored_status, result = _failure_fallback(paper, exc)
        task.status = TaskRecord.Status.FAILED
        task.error = sanitize_task_error(exc)
        task.progress = 100
        task.stage = "failed"
        task.result = {**_dict_result(task.result), **result}
        task.save(update_fields=["status", "error", "progress", "stage", "result", "updated_at"])
        paper.status = restored_status
        paper.save(update_fields=["status", "updated_at"])
        raise


def _failure_fallback(paper: Paper, exc: Exception) -> tuple[str, dict[str, object]]:
    active_deep_profile = paper.deep_profiles.filter(is_active=True).first()
    active_light_profile = paper.light_profiles.filter(is_active=True).first()
    restored_status = Paper.Status.NEEDS_REVIEW
    result: dict[str, object] = {
        "paper_id": paper.id,
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


def _process_deep_profile(paper: Paper, task: TaskRecord) -> DeepProcessResult:
    task.status = TaskRecord.Status.RUNNING
    task.progress = 15
    task.stage = "parsing_pdf"
    task.save(update_fields=["status", "progress", "stage", "updated_at"])

    paper.status = Paper.Status.DEEP_PROCESSING
    paper.save(update_fields=["status", "updated_at"])

    task_result = _dict_result(task.result)
    parsed = _validate_deep_parse_result(
        get_deep_parser_provider().parse(
            DeepParserInput.from_paper(paper, guidance=str(task_result.get("guidance", "")))
        )
    )

    with transaction.atomic():
        locked_paper = Paper.objects.select_for_update().get(pk=paper.pk)
        list(PaperDeepProfile.objects.select_for_update().filter(paper=locked_paper))
        PaperDeepProfile.objects.filter(paper=locked_paper, is_active=True).update(is_active=False)
        version = (
            PaperDeepProfile.objects.filter(paper=locked_paper).aggregate(max_version=Max("version"))["max_version"] or 0
        ) + 1
        profile = PaperDeepProfile.objects.create(
            paper=locked_paper,
            version=version,
            is_active=True,
            parser_name=parsed.parser_name,
            summary=parsed.summary,
            sections=parsed.sections,
            figures=parsed.figures,
            formulas=parsed.formulas,
            code_suggestions=parsed.code_suggestions,
            reproduction_notes=parsed.reproduction_notes,
        )

        locked_paper.status = Paper.Status.DEEP_READY
        locked_paper.save(update_fields=["status", "updated_at"])

        task.status = TaskRecord.Status.SUCCESS
        task.progress = 100
        task.stage = "deep_ready"
        task.result = {
            "paper_id": paper.id,
            "deep_profile_id": profile.id,
            "parser_name": profile.parser_name,
            "placeholder": False,
            "annotation_validation": validate_annotation_anchors(
                paper=locked_paper,
                deep_profile=profile,
                reason="deep_profile_created",
            ),
        }
        guidance = str(task_result.get("guidance", "")).strip()
        if guidance:
            task.result["guidance"] = guidance
        task.save(update_fields=["status", "progress", "stage", "result", "updated_at"])

    paper.refresh_from_db()
    return DeepProcessResult(paper=paper, profile=profile, task=task)


def _validate_deep_parse_result(parsed):
    errors: list[str] = []
    if not getattr(parsed, "parser_name", "").strip():
        errors.append("parser_name is required")
    if not isinstance(getattr(parsed, "summary", None), str) or not parsed.summary.strip():
        errors.append("summary is required")
    elif _contains_forbidden_deep_output(parsed.summary):
        errors.append("summary contains internal provider or storage details")
    if not isinstance(getattr(parsed, "reproduction_notes", None), str) or not parsed.reproduction_notes.strip():
        errors.append("reproduction_notes is required")
    for field_name in ("sections", "figures", "formulas", "code_suggestions"):
        value = getattr(parsed, field_name, None)
        if not isinstance(value, list):
            errors.append(f"{field_name} must be a list")
            continue
        if field_name == "sections" and not value:
            errors.append("sections must not be empty")
            continue
        invalid_items = [index for index, item in enumerate(value) if not isinstance(item, dict)]
        if invalid_items:
            errors.append(f"{field_name} entries must be objects")
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            _validate_json_safe(errors, field_name, index, item)
            if field_name == "sections":
                _validate_section(errors, index, item)
            elif field_name == "figures":
                _validate_required_string(errors, field_name, index, item, "id")
                _validate_required_string(errors, field_name, index, item, "caption")
                _validate_nullable_int(errors, field_name, index, item, "page", min_value=1)
                _validate_required_string(errors, field_name, index, item, "note")
            elif field_name == "formulas":
                _validate_required_string(errors, field_name, index, item, "id")
                _validate_required_string(errors, field_name, index, item, "latex")
                _validate_required_string(errors, field_name, index, item, "text")
                _validate_required_string(errors, field_name, index, item, "note")
                if "latex" in item and not isinstance(item["latex"], str):
                    errors.append(f"formulas[{index}].latex must be JSON-safe")
            elif field_name == "code_suggestions":
                _validate_required_string(errors, field_name, index, item, "title")
                _validate_required_string(errors, field_name, index, item, "note")
                if "score" in item and not isinstance(item["score"], int):
                    errors.append(f"code_suggestions[{index}].score must be an integer")
                if "quality" in item and not isinstance(item["quality"], dict):
                    errors.append(f"code_suggestions[{index}].quality must be an object")
                if "needs_review" in item and not isinstance(item["needs_review"], bool):
                    errors.append(f"code_suggestions[{index}].needs_review must be a boolean")
    sections = getattr(parsed, "sections", None)
    if isinstance(sections, list) and len(sections) == len(DEEP_SECTION_TITLES):
        titles = [item.get("title") for item in sections if isinstance(item, dict)]
        if titles != DEEP_SECTION_TITLES:
            errors.append("sections must use the stable titles: " + ", ".join(DEEP_SECTION_TITLES))
    for field_name in ("figures", "formulas"):
        value = getattr(parsed, field_name, None)
        if isinstance(value, list):
            _validate_unique_ids(errors, field_name, value)
    if errors:
        raise ValueError("Invalid deep parse result: " + "; ".join(errors))
    return parsed


def _ensure_deep_processable(paper: Paper) -> None:
    if not paper.source_pdf_path:
        raise DeepProcessingUnavailable("Deep processing requires an uploaded PDF.")
    if paper.status not in PROCESSABLE_STATUSES:
        raise DeepProcessingUnavailable(f"Paper status '{paper.status}' cannot start deep processing.")


def _dict_result(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _clean_guidance(value: str) -> str:
    return " ".join(str(value or "").strip().split())[:500]


def _validate_required_string(errors: list[str], field_name: str, index: int, item: dict[str, object], key: str) -> None:
    if not isinstance(item.get(key), str) or not str(item.get(key)).strip():
        errors.append(f"{field_name}[{index}].{key} is required")


def _validate_section(errors: list[str], index: int, item: dict[str, object]) -> None:
    if not isinstance(item.get("index"), int):
        errors.append(f"sections[{index}].index must be an integer")
    _validate_required_string(errors, "sections", index, item, "title")
    _validate_required_string(errors, "sections", index, item, "summary")
    if _contains_forbidden_deep_output(str(item.get("summary", ""))):
        errors.append(f"sections[{index}].summary contains internal provider or storage details")
    if "quality_score" in item and not isinstance(item["quality_score"], int):
        errors.append(f"sections[{index}].quality_score must be an integer")
    if "quality" in item and not isinstance(item["quality"], dict):
        errors.append(f"sections[{index}].quality must be an object")
    page_start = item.get("page_start")
    page_end = item.get("page_end")
    _validate_nullable_int(errors, "sections", index, item, "page_start", min_value=1)
    _validate_nullable_int(errors, "sections", index, item, "page_end", min_value=1)
    if isinstance(page_start, int) and isinstance(page_end, int) and page_end < page_start:
        errors.append(f"sections[{index}].page_end must be greater than or equal to page_start")


def _validate_nullable_int(
    errors: list[str],
    field_name: str,
    index: int,
    item: dict[str, object],
    key: str,
    *,
    min_value: int | None = None,
) -> None:
    if key not in item:
        errors.append(f"{field_name}[{index}].{key} is required")
        return
    value = item.get(key)
    if value is None:
        return
    if not isinstance(value, int):
        errors.append(f"{field_name}[{index}].{key} must be an integer or null")
        return
    if min_value is not None and value < min_value:
        errors.append(f"{field_name}[{index}].{key} must be greater than or equal to {min_value} or null")


def _contains_forbidden_deep_output(value: str) -> bool:
    lowered = value.lower()
    return any(pattern in lowered for pattern in FORBIDDEN_DEEP_OUTPUT_PATTERNS)


def _validate_unique_ids(errors: list[str], field_name: str, values: list[dict[str, object]]) -> None:
    ids = [item.get("id") for item in values if isinstance(item.get("id"), str) and str(item.get("id")).strip()]
    if len(ids) != len(set(ids)):
        errors.append(f"{field_name} id values must be unique")


def _validate_json_safe(errors: list[str], field_name: str, index: int, item: dict[str, object]) -> None:
    try:
        json.dumps(item)
    except (TypeError, ValueError):
        for key, value in item.items():
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                errors.append(f"{field_name}[{index}].{key} must be JSON-safe")
