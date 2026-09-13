from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.agent_access.contracts import SourceKind
from apps.agent_access.models import AgentAccessToken, ResearchContextBundle
from apps.materials.models import Evidence, Material, MaterialVersion
from apps.materials.services import set_external_agent_access


@override_settings(EXTERNAL_AGENT_ACCESS_ENABLED=True)
class ContextBundleApiTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="bundle-owner")
        self.member = get_user_model().objects.create_user(username="bundle-member")
        self.material = Material.objects.create(
            owner=self.owner,
            title="FNO 人工记录",
            visibility="team",
            source_kind=SourceKind.HUMAN_RECORD,
        )
        self.version = self.add_version(1, "old Fourier operator evidence", "c")
        set_external_agent_access(self.owner, self.material.pk, allowed=True)
        _, self.raw = AgentAccessToken.issue(
            owner=self.member,
            name="bundle client",
            scopes=["evidence:read"],
        )

    def add_version(self, number, text, digest_char):
        version = MaterialVersion.objects.create(
            material=self.material,
            number=number,
            sha256=digest_char * 64,
            filename=f"v{number}.md",
            format="md",
            storage_key=f"objects/v{number}",
            size=len(text),
            status="ready",
            created_by=self.owner,
        )
        Evidence.objects.create(version=version, ordinal=1, line_start=1, line_end=1, text=text)
        return version

    def auth(self, raw=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {raw or self.raw}"}

    def build(self, **payload):
        return self.client.post(
            "/api/v1/context-bundles",
            {"question": "Fourier operator", "material_ids": [self.material.pk], "limit": 5, **payload},
            content_type="application/json",
            secure=True,
            **self.auth(),
        )

    def test_build_freezes_keyword_manifest_source_kind_and_digest(self):
        response = self.build()
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["retrieval_manifest"]["mode"], "keyword")
        self.assertEqual(payload["retrieval_manifest"]["retriever_version"], "keyword-v1")
        self.assertFalse(payload["retrieval_manifest"]["degraded"])
        self.assertEqual(payload["evidence"][0]["source"]["source_kind"], SourceKind.HUMAN_RECORD)
        self.assertEqual(payload["evidence"][0]["source"]["identity"]["version_id"], self.version.pk)
        self.assertTrue(payload["content_digest"].startswith("sha256:"))
        self.assertIn("cannot recall", payload["warnings"][0])

    def test_new_version_does_not_silently_replace_frozen_evidence(self):
        created = self.build().json()
        old_evidence = created["evidence"][0]
        self.add_version(2, "new Fourier operator evidence", "d")
        response = self.client.get(
            f"/api/v1/context-bundles/{created['bundle_id']}", secure=True, **self.auth()
        )
        self.assertEqual(response.status_code, 200)
        retrieved = response.json()
        self.assertEqual(retrieved["evidence"][0], old_evidence)
        self.assertIn("source_version_not_latest", [row.get("code") for row in retrieved["warnings"] if isinstance(row, dict)])

    def test_revocation_blocks_refetch_without_returning_frozen_excerpt(self):
        created = self.build().json()
        set_external_agent_access(self.owner, self.material.pk, allowed=False)
        response = self.client.get(
            f"/api/v1/context-bundles/{created['bundle_id']}", secure=True, **self.auth()
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "bundle_source_unavailable")
        self.assertNotIn("old Fourier operator evidence", response.content.decode())
        self.assertTrue(ResearchContextBundle.objects.filter(bundle_id=created["bundle_id"]).exists())

    def test_visibility_change_is_rechecked_for_team_member(self):
        created = self.build().json()
        self.material.visibility = "private"
        self.material.save(update_fields=["visibility"])
        response = self.client.get(
            f"/api/v1/context-bundles/{created['bundle_id']}", secure=True, **self.auth()
        )
        self.assertEqual(response.status_code, 409)

    def test_another_user_cannot_fetch_bundle_by_id(self):
        created = self.build().json()
        outsider = get_user_model().objects.create_user(username="bundle-outsider")
        _, raw = AgentAccessToken.issue(owner=outsider, name="outsider", scopes=["evidence:read"])
        response = self.client.get(
            f"/api/v1/context-bundles/{created['bundle_id']}", secure=True, **self.auth(raw)
        )
        self.assertEqual(response.status_code, 404)

    def test_digest_tampering_fails_closed(self):
        created = self.build().json()
        ResearchContextBundle.objects.filter(bundle_id=created["bundle_id"]).update(question="tampered")
        response = self.client.get(
            f"/api/v1/context-bundles/{created['bundle_id']}", secure=True, **self.auth()
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "bundle_integrity_error")

    def test_unapproved_explicit_scope_is_rejected_without_content(self):
        set_external_agent_access(self.owner, self.material.pk, allowed=False)
        response = self.build()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "bundle_source_unavailable")
        self.assertNotIn("FNO", response.content.decode())
