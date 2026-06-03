from __future__ import annotations

from django.db import models

from apps.library.models import KnowledgeSpace


class KnowledgeSpaceRelation(models.Model):
    class RelationType(models.TextChoices):
        RELATED = "related", "Related"
        PREREQUISITE = "prerequisite", "Prerequisite"
        EXTENDS = "extends", "Extends"
        COMPETES = "competes", "Competes"
        APPLICATION = "application", "Application"

    source_space = models.ForeignKey(KnowledgeSpace, related_name="outgoing_relations", on_delete=models.CASCADE)
    target_space = models.ForeignKey(KnowledgeSpace, related_name="incoming_relations", on_delete=models.CASCADE)
    relation_type = models.CharField(max_length=32, choices=RelationType.choices, default=RelationType.RELATED)
    weight = models.FloatField(default=1.0)
    evidence_json = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source_space_id", "target_space_id"]
        unique_together = [("source_space", "target_space", "relation_type")]

    def __str__(self) -> str:
        return f"{self.source_space_id}->{self.target_space_id}:{self.relation_type}"


class DirectionMapSnapshot(models.Model):
    root_space = models.ForeignKey(KnowledgeSpace, related_name="direction_map_snapshots", on_delete=models.CASCADE)
    version = models.PositiveIntegerField(default=1)
    nodes_json = models.JSONField(default=list, blank=True)
    edges_json = models.JSONField(default=list, blank=True)
    generator = models.CharField(max_length=80, default="manual_v1")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-id"]
        unique_together = [("root_space", "version")]

    def __str__(self) -> str:
        return f"{self.root_space_id}:map:v{self.version}"
