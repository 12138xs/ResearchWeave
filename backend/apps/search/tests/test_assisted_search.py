import json
import os
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.materials.models import Evidence, Material, MaterialVersion
from apps.tasks.models import TaskRecord


def answer(payload):
    return SimpleNamespace(content=json.dumps(payload), model="MiniMax-M3", usage={"total_tokens": 12})


class AssistedSearchTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="assisted-owner")
        self.other = get_user_model().objects.create_user(username="assisted-other")
        self.client.force_login(self.owner)
        self.material = Material.objects.create(title="PINN", owner=self.owner, visibility="team")
        self.version = MaterialVersion.objects.create(material=self.material, number=1, sha256="a" * 64,
            filename="note.md", format="md", size=10, storage_key="unused.md", status="ready", created_by=self.owner)
        self.evidence = Evidence.objects.create(version=self.version, ordinal=1, line_start=1, line_end=2,
            text="Physics informed neural networks solve partial differential equations using residual losses.")

    def search(self, query="物理约束网络"):
        return self.client.post("/api/search/evidence/assist/", {"q": query}, content_type="application/json")

    @patch("apps.search.assisted.call_minimax_chat")
    def test_cross_language_expansion_and_owned_usage_record(self, model):
        model.side_effect = [answer({"queries": ["physics informed neural networks", "PINN"]}),
                             answer({"evidence_ids": [self.evidence.pk]})]
        response = self.search()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "assisted_keyword")
        self.assertEqual(response.json()["results"][0]["evidence_id"], self.evidence.pk)
        self.assertEqual(model.call_count, 2)
        self.assertTrue(all(call.kwargs["model"] == "MiniMax-M3" for call in model.call_args_list))
        task = TaskRecord.objects.get(task_type="evidence_assist")
        self.assertEqual(task.created_by, self.owner)
        self.assertEqual(task.result["total_tokens"], 24)

    @patch("apps.search.assisted.call_minimax_chat")
    def test_forged_ids_are_rejected_and_fallback_is_visible(self, model):
        model.side_effect = [answer({"queries": ["PINN"]}), answer({"evidence_ids": [999999]})]
        result = self.search("PINN").json()
        self.assertEqual(result["mode"], "keyword")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["results"][0]["evidence_id"], self.evidence.pk)

    @patch("apps.search.assisted.call_minimax_chat", side_effect=RuntimeError("secret gateway token"))
    def test_failure_falls_back_without_exposing_provider_error(self, model):
        result = self.search("PINN").json()
        self.assertTrue(result["degraded"])
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("secret", TaskRecord.objects.get(task_type="evidence_assist").error)

    @patch("apps.search.assisted.call_minimax_chat")
    def test_permissions_rechecked_after_model_call(self, model):
        self.client.force_login(self.other)
        def choose(*args, **kwargs):
            if model.call_count == 1:
                return answer({"queries": ["PINN"]})
            self.material.visibility = "private"
            self.material.save()
            return answer({"evidence_ids": [self.evidence.pk]})
        model.side_effect = choose
        result = self.search("PINN").json()
        self.assertEqual(result["results"], [])
        self.assertFalse(result["degraded"])

    @patch("apps.search.assisted.call_minimax_chat")
    def test_private_evidence_not_sent_to_another_user(self, model):
        self.material.visibility = "private"
        self.material.save()
        self.client.force_login(self.other)
        model.return_value = answer({"queries": ["PINN"]})
        self.assertEqual(self.search("PINN").json()["results"], [])
        model.assert_called_once()
        self.assertNotIn(self.evidence.text, str(model.call_args))

    @patch("apps.search.assisted.call_minimax_chat")
    def test_repeated_clicks_are_throttled(self, model):
        model.side_effect = [answer({"queries": ["PINN"]}), answer({"evidence_ids": [self.evidence.pk]})]
        self.assertEqual(self.search("PINN").status_code, 200)
        self.assertEqual(self.search("PINN").status_code, 429)
        self.assertEqual(model.call_count, 2)

    @patch("apps.search.assisted.call_minimax_chat")
    def test_no_model_call_for_anonymous_or_invalid_query(self, model):
        self.assertEqual(self.search("").status_code, 400)
        self.client.logout()
        self.assertIn(self.search().status_code, (401, 403))
        model.assert_not_called()

    @patch("apps.search.assisted.call_minimax_chat")
    def test_empty_selection_does_not_invent_evidence(self, model):
        model.side_effect = [answer({"queries": ["PINN"]}), answer({"evidence_ids": []})]
        result = self.search("PINN").json()
        self.assertEqual(result["results"], [])
        self.assertFalse(result["degraded"])


@skipUnless(os.getenv("RWV_LIVE_MINIMAX") == "1", "需显式启用服务器真实模型验收")
class LiveAssistedSearchTests(TestCase):
    def test_live_m3_recovers_cross_language_source(self):
        user = get_user_model().objects.create_user(username="live-search-fixture")
        evidence_ids = []
        for index, (title, text) in enumerate([
            ("PINN demonstration", "Physics informed neural networks (PINNs) use partial differential equation residuals and boundary conditions in their training loss."),
            ("Materials demonstration", "Crystal structure descriptors are used for screening candidate battery materials."),
        ], 1):
            material = Material.objects.create(title=title, owner=user, visibility="team")
            version = MaterialVersion.objects.create(material=material, number=1, sha256=str(index) * 64,
                filename="synthetic.md", format="md", size=len(text), storage_key="unused.md", status="ready", created_by=user)
            evidence_ids.append(Evidence.objects.create(version=version, ordinal=1, line_start=1, line_end=1, text=text).pk)
        self.client.force_login(user)
        query = "用偏微分方程残差约束神经网络训练的相关材料"
        baseline = self.client.get("/api/search/evidence/", {"q": query}).json()
        self.assertEqual(baseline["results"], [])
        response = self.client.post("/api/search/evidence/assist/", {"q": query}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "assisted_keyword")
        self.assertFalse(response.json()["degraded"])
        self.assertIn(evidence_ids[0], [row["evidence_id"] for row in response.json()["results"]])
        task = TaskRecord.objects.get(task_type="evidence_assist", created_by=user)
        print(f"Live M3: keyword=0, enhanced={len(response.json()['results'])}, tokens={task.result['total_tokens']}")
