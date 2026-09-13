from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.agent_access.contracts import (
    SourceContractError,
    SourceKind,
    SourceType,
    material_evidence_reference,
    source_reference,
)
from apps.materials.models import Evidence, Material, MaterialVersion
from apps.materials.selectors import externally_accessible_materials
from apps.materials.services import set_external_agent_access


@override_settings(EXTERNAL_AGENT_ACCESS_ENABLED=True)
class ExternalSourceBoundaryTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="source-owner")
        self.member = get_user_model().objects.create_user(username="source-member")
        self.material = Material.objects.create(
            title="人工整理的 PDE 记录",
            owner=self.owner,
            visibility="team",
            source_kind=SourceKind.HUMAN_RECORD,
        )

    def test_team_visibility_does_not_grant_external_access(self):
        self.assertFalse(externally_accessible_materials(self.owner).filter(pk=self.material.pk).exists())
        self.assertFalse(externally_accessible_materials(self.member).filter(pk=self.material.pk).exists())

    def test_only_owner_can_explicitly_approve_external_access(self):
        with self.assertRaises(Material.DoesNotExist):
            set_external_agent_access(self.member, self.material.pk, allowed=True)
        set_external_agent_access(self.owner, self.material.pk, allowed=True)
        self.assertTrue(externally_accessible_materials(self.owner).filter(pk=self.material.pk).exists())
        self.assertTrue(externally_accessible_materials(self.member).filter(pk=self.material.pk).exists())
        set_external_agent_access(self.owner, self.material.pk, allowed=False)
        self.assertFalse(externally_accessible_materials(self.member).filter(pk=self.material.pk).exists())

    def test_unclassified_source_cannot_be_approved(self):
        self.material.source_kind = SourceKind.UNCLASSIFIED
        self.material.save(update_fields=["source_kind"])
        with self.assertRaises(ValidationError):
            set_external_agent_access(self.owner, self.material.pk, allowed=True)

    @override_settings(EXTERNAL_AGENT_ACCESS_ENABLED=False)
    def test_feature_switch_blocks_all_external_candidates(self):
        set_external_agent_access(self.owner, self.material.pk, allowed=True)
        self.assertFalse(externally_accessible_materials(self.owner).exists())

    def test_material_evidence_reference_uses_stored_kind_and_exact_ids(self):
        set_external_agent_access(self.owner, self.material.pk, allowed=True)
        version = MaterialVersion.objects.create(
            material=self.material,
            number=1,
            sha256="a" * 64,
            filename="paper.pdf",
            format="pdf",
            storage_key="objects/example",
            size=1,
            status="ready",
            created_by=self.owner,
        )
        evidence = Evidence.objects.create(version=version, ordinal=1, text="recorded observation")
        reference = material_evidence_reference(evidence)
        self.assertEqual(reference["source_kind"], SourceKind.HUMAN_RECORD)
        self.assertEqual(
            reference["identity"],
            {"material_id": self.material.pk, "version_id": version.pk, "evidence_id": evidence.pk},
        )

    def test_native_sources_reject_fabricated_material_identity(self):
        reference = source_reference(
            source_type=SourceType.EXPERIMENT_RUN,
            source_kind=SourceKind.EXPERIMENT_OBSERVATION,
            display_name="run 7",
            experiment_project_id=3,
            experiment_run_id=7,
        )
        self.assertEqual(reference["identity"], {"experiment_project_id": 3, "experiment_run_id": 7})
        with self.assertRaises(SourceContractError):
            source_reference(
                source_type=SourceType.EXPERIMENT_RUN,
                source_kind=SourceKind.EXPERIMENT_OBSERVATION,
                display_name="run 7",
                material_id=3,
                version_id=4,
                evidence_id=7,
            )
