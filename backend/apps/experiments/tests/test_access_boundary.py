from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.assistant.models import AssistantSession
from apps.experiments.models import ExperimentProject, ExperimentRun
from apps.search.models import SearchIndexEntry
from apps.tasks.models import TaskRecord


class ResearchAccessBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user(username="alice")
        cls.bob = get_user_model().objects.create_user(username="bob")
        cls.project = ExperimentProject.objects.create(title="个人实验", owner=cls.alice)
        cls.run = ExperimentRun.objects.create(project=cls.project, created_by=cls.alice, notes="私密观察")

    def login(self, user=None):
        self.client.force_login(user or self.alice)

    def test_anonymous_cannot_read_materials_or_files(self):
        for url in [
            "/api/papers/", "/api/papers/1/pdf/", "/api/documents/",
            "/api/experiments/", "/api/search/", "/api/tasks/",
            "/api/tasks/status/", "/api/quality/issues/", "/api/knowledge-spaces/",
            "/api/catalog/stats/", "/api/keywords/", "/api/keywords/suggest/",
            "/api/assets/images/missing.png",
        ]:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (401, 403))

    def test_creation_defaults_to_private_and_cannot_forge_owner(self):
        self.login()
        response = self.client.post("/api/experiments/", {
            "title": "新实验", "owner": self.bob.pk,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["owner"], self.alice.pk)
        self.assertEqual(response.json()["visibility"], "private")

    def test_owner_can_read_and_update_project_and_run(self):
        self.login()
        self.assertEqual(self.client.get(f"/api/experiments/{self.project.pk}/").status_code, 200)
        response = self.client.patch(f"/api/experiments/runs/{self.run.pk}/", {
            "notes": "已更新", "created_by": self.bob.pk,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.run.refresh_from_db()
        self.assertEqual(self.run.notes, "已更新")
        self.assertEqual(self.run.created_by_id, self.alice.pk)

    def test_other_member_cannot_list_read_write_or_execute_private_experiment(self):
        self.login(self.bob)
        self.assertEqual(self.client.get("/api/experiments/").json()["count"], 0)
        urls = [f"/api/experiments/{self.project.pk}/", f"/api/experiments/{self.project.pk}/runs/",
                f"/api/experiments/runs/{self.run.pk}/"]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        with patch("apps.experiments.views.enqueue_experiment_run") as enqueue:
            response = self.client.post(f"/api/experiments/runs/{self.run.pk}/execute/")
            self.assertEqual(response.status_code, 404)
            enqueue.assert_not_called()
        self.assertEqual(self.client.patch(urls[0], {"owner": self.bob.pk},
                                          content_type="application/json").status_code, 404)
        self.assertEqual(self.client.post(urls[1], {"notes": "越权"},
                                         content_type="application/json").status_code, 404)

    def test_team_project_readable_but_not_editable_by_other_member(self):
        self.project.visibility = "team"
        self.project.save()
        self.login(self.bob)
        url = f"/api/experiments/{self.project.pk}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {"objective": "越权"},
                                          content_type="application/json").status_code, 404)

    def test_search_checks_current_access_even_with_stale_index(self):
        self.project.visibility = "team"
        self.project.save()
        SearchIndexEntry.objects.create(object_type="experiment", object_id=self.project.pk,
                                        title="个人实验", body="私密内容")
        self.login(self.bob)
        self.assertEqual(self.client.get("/api/search/?scope=experiment").json()["count"], 1)
        self.project.visibility = "private"
        self.project.save()
        self.assertEqual(self.client.get("/api/search/?scope=experiment").json()["count"], 0)
        self.login()
        self.assertEqual(self.client.get("/api/search/?scope=experiment").json()["count"], 1)

    def test_task_result_and_polling_do_not_leak_other_members_data(self):
        task = TaskRecord.objects.create(task_type="experiment_run_execute", object_type="experiment_run",
                                        object_id=self.run.pk, created_by=self.alice, result={"notes": "私密"})
        self.login(self.bob)
        self.assertEqual(self.client.get(f"/api/tasks/{task.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/tasks/status/?ids={task.pk}").json()["tasks"], [])
        self.assertEqual(self.client.get("/api/tasks/").json()["summary"]["total"], 0)
        self.login()
        self.assertEqual(self.client.get(f"/api/tasks/{task.pk}/").status_code, 200)

    def test_private_image_access_is_owner_scoped_and_default_upload_is_team_visible(self):
        with TemporaryDirectory() as tmpdir, override_settings(STORAGE_ROOT=Path(tmpdir)):
            self.login()
            urls = []
            for visibility in ("private", "team"):
                image = SimpleUploadedFile("plot.png", b"\x89PNG\r\n\x1a\ntest", content_type="image/png")
                response = self.client.post("/api/storage/upload-image/", {"image": image, "visibility": visibility})
                self.assertEqual(response.status_code, 201)
                urls.append(response.json()["url"])
            own = self.client.get(urls[0])
            self.assertEqual(own.status_code, 200)
            self.assertTrue(b"".join(own.streaming_content))
            self.login(self.bob)
            self.assertEqual(self.client.get(urls[0]).status_code, 404)
            shared = self.client.get(urls[1])
            self.assertEqual(shared.status_code, 200)
            self.assertTrue(b"".join(shared.streaming_content))

    def test_existing_unregistered_image_remains_team_readable(self):
        self.login()
        with TemporaryDirectory() as tmpdir, override_settings(STORAGE_ROOT=Path(tmpdir)):
            target = Path(tmpdir) / "objects/images/legacy.png"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"legacy")
            response = self.client.get("/api/assets/images/legacy.png")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"legacy")

    def test_sessions_remain_private(self):
        session = AssistantSession.objects.create(title="私密会话", created_by=self.alice)
        self.login(self.bob)
        self.assertEqual(self.client.get(f"/api/assistant/sessions/{session.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/assistant/sessions/{session.pk}/messages/",
                                         {"question": "读取"}).status_code, 404)

    def test_scope_cannot_reference_another_members_private_experiment(self):
        self.login(self.bob)
        response = self.client.post("/api/assistant/sessions/", {
            "title": "新会话", "scope_json": {"experiment_ids": [self.project.pk]},
        }, content_type="application/json")
        self.assertEqual(response.status_code, 400)
