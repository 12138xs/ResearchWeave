from __future__ import annotations

from django.db import transaction

from apps.library.models import KnowledgeSpace
from apps.research_map.models import DirectionMapSnapshot, KnowledgeSpaceRelation
from apps.research_map.selectors import direction_map_payload
from apps.tasks.models import TaskRecord


def generate_direction_map(root_space: KnowledgeSpace) -> DirectionMapSnapshot:
    payload = direction_map_payload(root_space)
    edges = payload["relations"]
    nodes = [payload["root"], *payload["children"]]
    with transaction.atomic():
        DirectionMapSnapshot.objects.filter(root_space=root_space, is_active=True).update(is_active=False)
        latest_version = (
            DirectionMapSnapshot.objects.filter(root_space=root_space).order_by("-version").values_list("version", flat=True).first()
            or 0
        )
        return DirectionMapSnapshot.objects.create(
            root_space=root_space,
            version=latest_version + 1,
            nodes_json=nodes,
            edges_json=edges,
            generator="rule_based_v1",
            is_active=True,
        )


def enqueue_direction_map_generation(root_space: KnowledgeSpace, user) -> TaskRecord:
    task = TaskRecord.objects.create(
        task_type="direction_map_generate",
        object_type="knowledge_space",
        object_id=root_space.id,
        created_by=user if getattr(user, "is_authenticated", False) else None,
        stage="queued",
    )
    from apps.research_map.tasks import generate_direction_map_task

    try:
        generate_direction_map_task.delay(root_space.id, task.id)
    except Exception as exc:
        task.status = TaskRecord.Status.FAILED
        task.stage = "publish_failed"
        task.error = str(exc)
        task.save(update_fields=["status", "stage", "error", "updated_at"])
        raise
    return task


def create_relation(source_space: KnowledgeSpace, target_space: KnowledgeSpace, relation_type: str, weight: float = 1.0):
    return KnowledgeSpaceRelation.objects.create(
        source_space=source_space,
        target_space=target_space,
        relation_type=relation_type,
        weight=weight,
    )
