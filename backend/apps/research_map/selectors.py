from __future__ import annotations

from apps.documents.models import Document
from apps.experiments.models import ExperimentProject
from apps.library.models import KnowledgeSpace
from apps.papers.models import Paper
from apps.quality.models import QualityIssue
from apps.research_map.models import DirectionMapSnapshot, KnowledgeSpaceRelation


def direction_map_payload(root_space: KnowledgeSpace) -> dict[str, object]:
    latest_snapshot = (
        DirectionMapSnapshot.objects.filter(root_space=root_space, is_active=True)
        .order_by("-version", "-created_at")
        .first()
    )
    space_ids = [root_space.id, *root_space.descendant_ids()]
    relations = KnowledgeSpaceRelation.objects.select_related("source_space", "target_space").filter(
        is_active=True,
        source_space_id__in=space_ids,
    )
    return {
        "root": _space_node(root_space),
        "children": [_space_node(space) for space in KnowledgeSpace.objects.filter(parent=root_space, is_active=True)],
        "relations": [
            {
                "id": relation.id,
                "source_space": relation.source_space_id,
                "source_name": relation.source_space.name,
                "target_space": relation.target_space_id,
                "target_name": relation.target_space.name,
                "relation_type": relation.relation_type,
                "weight": relation.weight,
                "evidence_json": relation.evidence_json,
            }
            for relation in relations
        ],
        "snapshot": _snapshot_payload(latest_snapshot) if latest_snapshot else None,
    }


def _space_node(space: KnowledgeSpace) -> dict[str, object]:
    return {
        "id": space.id,
        "name": space.name,
        "slug": space.slug,
        "description": space.description,
        "paper_count": Paper.objects.filter(space=space).count(),
        "document_count": Document.objects.filter(space=space).count(),
        "experiment_count": ExperimentProject.objects.filter(space=space).count(),
        "open_quality_issue_count": QualityIssue.objects.filter(
            status=QualityIssue.Status.OPEN,
            object_type__in=["paper", "document", "experiment"],
        ).count(),
    }


def _snapshot_payload(snapshot: DirectionMapSnapshot) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "root_space": snapshot.root_space_id,
        "version": snapshot.version,
        "nodes_json": snapshot.nodes_json,
        "edges_json": snapshot.edges_json,
        "generator": snapshot.generator,
        "is_active": snapshot.is_active,
        "created_at": snapshot.created_at,
    }
