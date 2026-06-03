from __future__ import annotations

from rest_framework import serializers

from apps.research_map.models import DirectionMapSnapshot, KnowledgeSpaceRelation


class KnowledgeSpaceRelationSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source_space.name", read_only=True)
    target_name = serializers.CharField(source="target_space.name", read_only=True)

    class Meta:
        model = KnowledgeSpaceRelation
        fields = [
            "id",
            "source_space",
            "source_name",
            "target_space",
            "target_name",
            "relation_type",
            "weight",
            "evidence_json",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DirectionMapSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = DirectionMapSnapshot
        fields = [
            "id",
            "root_space",
            "version",
            "nodes_json",
            "edges_json",
            "generator",
            "is_active",
            "created_at",
        ]
