from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import reverse

from apps.research_map.models import DirectionMapSnapshot, KnowledgeSpaceRelation


class ResearchMapContractTests(SimpleTestCase):
    def test_relation_and_snapshot_models_reuse_knowledge_spaces(self) -> None:
        relation_fields = {field.name for field in KnowledgeSpaceRelation._meta.fields}
        snapshot_fields = {field.name for field in DirectionMapSnapshot._meta.fields}

        for field_name in {"source_space", "target_space", "relation_type", "weight", "evidence_json", "is_active"}:
            self.assertIn(field_name, relation_fields)

        for field_name in {"root_space", "version", "nodes_json", "edges_json", "generator", "is_active"}:
            self.assertIn(field_name, snapshot_fields)

        self.assertEqual(KnowledgeSpaceRelation.RelationType.PREREQUISITE, "prerequisite")

    def test_research_map_urls_are_nested_under_knowledge_spaces(self) -> None:
        self.assertEqual(reverse("knowledge-space-map", kwargs={"pk": 1}), "/api/knowledge-spaces/1/map/")
        self.assertEqual(
            reverse("knowledge-space-map-generate", kwargs={"pk": 1}),
            "/api/knowledge-spaces/1/map/generate/",
        )
