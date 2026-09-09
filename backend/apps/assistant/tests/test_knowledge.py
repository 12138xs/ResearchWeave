from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.assistant.knowledge import search_knowledge, source_allowed
from apps.documents.models import Document, DocumentVersion
from apps.materials.models import Material, MaterialVersion, Evidence


class KnowledgeTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="knowledge-owner")
        self.other = get_user_model().objects.create_user(username="knowledge-other")
        self.material = Material.objects.create(title="PINN", owner=self.owner, visibility="private")
        version = MaterialVersion.objects.create(material=self.material, number=1, sha256="a" * 64,
            filename="note.md", format="md", size=20, status="ready", created_by=self.owner)
        self.evidence = Evidence.objects.create(version=version, ordinal=1, text="PINN residual loss", line_start=1, line_end=1)
        document = Document.objects.create(title="PINN document")
        self.document = DocumentVersion.objects.create(document=document, markdown="PINN boundary conditions")

    def test_private_material_never_retrieved_for_other_user(self):
        rows = search_knowledge(self.other, {}, "PINN")
        self.assertEqual([row["type"] for row in rows], ["document"])
        self.assertFalse(source_allowed({"type": "material", "id": self.evidence.pk}, self.other))

    def test_explicit_scope_does_not_expand_to_legacy_sources(self):
        rows = search_knowledge(self.owner, {"material_ids": [self.material.pk]}, "PINN")
        self.assertEqual([row["type"] for row in rows], ["material"])
        self.assertIn("版本 1", rows[0]["location"])

    def test_explicit_empty_scope_is_empty(self):
        self.assertEqual(search_knowledge(self.owner, {"document_ids": []}, "PINN"), [])

    def test_legacy_current_version_and_source_snapshot(self):
        self.document.is_current = False
        self.document.save()
        newest = DocumentVersion.objects.create(document=self.document.document, version=2, markdown="PINN current text")
        rows = search_knowledge(self.other, {}, "PINN")
        self.assertEqual(rows[0]["id"], newest.pk)
        self.assertEqual(len(rows[0]["sha256"]), 64)
        self.assertTrue(source_allowed({"type": "document", "id": self.document.pk}, self.other))
