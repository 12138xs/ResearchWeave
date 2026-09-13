from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.agent_access.contracts import SourceKind
from apps.agent_access.models import AgentAccessToken, AgentAuditEvent
from apps.materials.models import Evidence, Material, MaterialVersion
from apps.materials.services import set_external_agent_access


@override_settings(EXTERNAL_AGENT_ACCESS_ENABLED=True)
class PersonalAccessTokenApiTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="pat-owner")
        self.member = get_user_model().objects.create_user(username="pat-member")
        self.team_material = self.material(self.owner, "团队人工记录", "team", SourceKind.HUMAN_RECORD)
        self.private_material = self.material(self.owner, "私有论文", "private", SourceKind.PAPER_FULLTEXT)

    def material(self, owner, title, visibility, source_kind):
        material = Material.objects.create(
            owner=owner,
            title=title,
            visibility=visibility,
            source_kind=source_kind,
        )
        version = MaterialVersion.objects.create(
            material=material,
            number=1,
            sha256=("a" if visibility == "team" else "b") * 64,
            filename="source.md",
            format="md",
            storage_key=f"objects/{visibility}",
            size=20,
            status="ready",
            created_by=owner,
        )
        Evidence.objects.create(
            version=version,
            ordinal=1,
            line_start=1,
            line_end=2,
            text=f"{title} 中的 Fourier operator evidence",
        )
        return material

    def issue(self, user=None, scopes=None, expires_at=None):
        return AgentAccessToken.issue(
            owner=user or self.owner,
            name="Codex laptop",
            scopes=scopes or ["materials:read", "evidence:read"],
            expires_at=expires_at,
        )

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_RESEARCHWEAVE_CLIENT": "contract-test/1"}

    def test_token_creation_requires_https_and_only_returns_secret_once(self):
        self.client.force_login(self.owner)
        payload = {"name": "Codex", "scopes": ["materials:read"]}
        insecure = self.client.post("/api/v1/tokens", payload, content_type="application/json")
        self.assertEqual(insecure.status_code, 403)
        self.assertEqual(AgentAccessToken.objects.count(), 0)

        created = self.client.post("/api/v1/tokens", payload, content_type="application/json", secure=True)
        self.assertEqual(created.status_code, 201)
        raw = created.json()["token"]
        record = AgentAccessToken.objects.get()
        self.assertTrue(raw.startswith(f"rwv_pat_{record.token_id.hex}."))
        self.assertNotEqual(record.secret_hash, raw)
        self.assertNotIn(raw, str(record.__dict__))

        listed = self.client.get("/api/v1/tokens", secure=True)
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn("token", listed.json()["results"][0])
        self.assertNotIn("secret_hash", listed.json()["results"][0])
        self.assertNotIn(raw, listed.content.decode())
        audit = AgentAuditEvent.objects.get(action="token.create")
        self.assertEqual((audit.user_id, audit.token_id, audit.status_code), (self.owner.pk, record.pk, 201))

    def test_unknown_or_expired_scopes_are_rejected(self):
        self.client.force_login(self.owner)
        unknown = self.client.post(
            "/api/v1/tokens",
            {"name": "future client", "scopes": ["runs:submit"]},
            content_type="application/json",
            secure=True,
        )
        self.assertEqual(unknown.status_code, 400)
        expired = self.client.post(
            "/api/v1/tokens",
            {"name": "expired", "scopes": ["materials:read"], "expires_at": (timezone.now() - timedelta(minutes=1)).isoformat()},
            content_type="application/json",
            secure=True,
        )
        self.assertEqual(expired.status_code, 400)

    def test_pat_is_rejected_over_plain_http_and_attempt_is_audited(self):
        _, raw = self.issue()
        response = self.client.get("/api/v1/me", **self.auth(raw))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "insecure_transport")
        event = AgentAuditEvent.objects.get()
        self.assertEqual((event.action, event.status_code, event.token_id), ("me.read", 401, None))

    def test_me_only_advertises_currently_implemented_capabilities(self):
        token, raw = self.issue(scopes=["materials:read"])
        response = self.client.get("/api/v1/me", secure=True, **self.auth(raw))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["capabilities"], ["materials.list", "materials.get"])
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)

    def test_scope_can_only_shrink_object_permissions(self):
        set_external_agent_access(self.owner, self.team_material.pk, allowed=True)
        set_external_agent_access(self.owner, self.private_material.pk, allowed=True)
        _, member_raw = self.issue(user=self.member, scopes=["materials:read"])
        response = self.client.get("/api/v1/materials", secure=True, **self.auth(member_raw))
        self.assertEqual(response.status_code, 200)
        ids = [row["material_id"] for row in response.json()["results"]]
        self.assertEqual(ids, [self.team_material.pk])

        _, evidence_only = self.issue(user=self.member, scopes=["evidence:read"])
        denied = self.client.get("/api/v1/materials", secure=True, **self.auth(evidence_only))
        self.assertEqual(denied.status_code, 403)
        event = AgentAuditEvent.objects.filter(token__owner=self.member, status_code=403).latest("pk")
        self.assertEqual(event.error_code, "scope_denied")

    def test_team_readable_material_is_hidden_until_owner_approves(self):
        _, raw = self.issue(user=self.member, scopes=["materials:read"])
        hidden = self.client.get("/api/v1/materials", secure=True, **self.auth(raw))
        self.assertEqual(hidden.json()["results"], [])

        self.client.force_login(self.owner)
        approved = self.client.patch(
            f"/api/v1/materials/{self.team_material.pk}/external-access",
            {"source_kind": SourceKind.HUMAN_RECORD, "allowed": True},
            content_type="application/json",
            secure=True,
        )
        self.assertEqual(approved.status_code, 200)
        self.client.logout()
        visible = self.client.get("/api/v1/materials", secure=True, **self.auth(raw))
        self.assertEqual([row["material_id"] for row in visible.json()["results"]], [self.team_material.pk])
        self.assertNotIn("file_url", str(visible.json()))

    def test_evidence_search_uses_external_filter_and_native_source_contract(self):
        set_external_agent_access(self.owner, self.team_material.pk, allowed=True)
        _, raw = self.issue(user=self.member, scopes=["evidence:read"])
        response = self.client.post(
            "/api/v1/evidence/search",
            {"q": "Fourier", "limit": 5},
            content_type="application/json",
            secure=True,
            **self.auth(raw),
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["source"]["source_type"], "material_evidence")
        self.assertEqual(result["source"]["source_kind"], SourceKind.HUMAN_RECORD)
        self.assertEqual(result["source"]["identity"]["material_id"], self.team_material.pk)
        self.assertNotIn("_evidence", result)
        self.assertNotIn("file_url", result)
        event = AgentAuditEvent.objects.get(action="evidence.search")
        self.assertEqual((event.returned_count, event.client), (1, "contract-test/1"))

    def test_revocation_takes_effect_on_next_request_and_is_audited(self):
        token, raw = self.issue(scopes=["materials:read"])
        self.assertEqual(self.client.get("/api/v1/materials", secure=True, **self.auth(raw)).status_code, 200)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.delete(f"/api/v1/tokens/{token.token_id}", secure=True).status_code, 204)
        self.client.logout()
        rejected = self.client.get("/api/v1/materials", secure=True, **self.auth(raw))
        self.assertEqual(rejected.status_code, 401)
        event = AgentAuditEvent.objects.filter(token=token, status_code=401).latest("pk")
        self.assertEqual(event.error_code, "token_revoked")

    @override_settings(EXTERNAL_AGENT_ACCESS_ENABLED=False)
    def test_feature_switch_disables_pat_routes(self):
        _, raw = self.issue(scopes=["materials:read"])
        response = self.client.get("/api/v1/materials", secure=True, **self.auth(raw))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "external_agent_disabled")
