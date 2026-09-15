import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Feedback


class FeedbackTests(TestCase):
    def setUp(self):
        self.alice = get_user_model().objects.create_user(username="feedback-alice")
        self.bob = get_user_model().objects.create_user(username="feedback-bob")
        self.client = APIClient()

    def post(self, content="建议改善布局", **extra):
        return self.client.post("/api/feedback/", {"content": content, "request_id": str(uuid.uuid4()), **extra}, format="json")

    def test_anonymous_cannot_read_or_write(self):
        self.assertIn(self.client.get("/api/feedback/").status_code, (401, 403))
        self.assertIn(self.post().status_code, (401, 403))

    def test_identity_time_mentions_and_team_visibility(self):
        self.client.force_authenticate(self.alice)
        result = self.post("@内置科研Agent 改进回答。 @知识文档，支持预览。", author=self.bob.pk,
                           author_name="伪造", created_at="2000-01-01T00:00:00Z", features=["settings"])
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.data["author_name"], self.alice.username)
        self.assertFalse(result.data["created_at"].startswith("2000"))
        self.assertEqual(result.data["features"], ["agent", "documents"])
        self.client.force_authenticate(self.bob)
        listing = self.client.get("/api/feedback/").data
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["results"][0]["id"], result.data["id"])
        self.assertNotIn("author", listing["results"][0])

    def test_idempotency_and_conflicting_reuse(self):
        self.client.force_authenticate(self.alice)
        request_id = str(uuid.uuid4())
        first = self.post(request_id=request_id)
        again = self.post(request_id=request_id)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.data["id"], again.data["id"])
        self.assertEqual(self.post("另一条", request_id=request_id).status_code, 409)
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.post(request_id=request_id).status_code, 409)
        self.assertEqual(Feedback.objects.count(), 1)

    def test_validation(self):
        self.client.force_authenticate(self.alice)
        for content in ["   ", "x" * 4001]:
            self.assertEqual(self.post(content).status_code, 400)
        self.assertEqual(self.post(request_id="invalid").status_code, 400)
        for page in ["²", "9" * 5000, "0", "-1", "a"]:
            self.assertEqual(self.client.get("/api/feedback/", {"page": page}).status_code, 400)

    def test_unknown_mentions_remain_plain_text_and_author_history_survives(self):
        self.client.force_authenticate(self.alice)
        result = self.post("@不存在 @论文库扩展 user@知识文档 <script>alert(1)</script>")
        self.assertEqual(result.data["features"], [])
        self.alice.delete()
        item = Feedback.objects.get()
        self.assertEqual(item.author_name, "feedback-alice")
        self.assertIsNone(item.author_id)

    def test_pagination(self):
        self.client.force_authenticate(self.alice)
        for index in range(21):
            self.post(str(index))
        page1 = self.client.get("/api/feedback/").data
        page2 = self.client.get("/api/feedback/?page=2").data
        self.assertEqual(len(page1["results"]), 20)
        self.assertEqual(len(page2["results"]), 1)
        self.assertEqual(page1["results"][0]["content"], "20")
        self.assertEqual(page2["results"][0]["content"], "0")
