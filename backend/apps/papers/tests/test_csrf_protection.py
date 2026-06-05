from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from apps.papers.models import Paper, PaperDeepProfile
from apps.papers.tests.test_paper_upload import sample_pdf_bytes


class PaperCsrfProtectionTests(TestCase):
    def csrf_token_for(self, client: Client) -> str:
        client.get("/api/me/")
        return client.cookies["csrftoken"].value

    def test_upload_rejects_missing_csrf_token_when_checks_are_enforced(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)
        client.login(username="member", password="member-password")
        pdf = SimpleUploadedFile("paper.pdf", sample_pdf_bytes(), content_type="application/pdf")

        response = client.post("/api/papers/upload/", {"file": pdf, "title": "Blocked"})

        self.assertEqual(response.status_code, 403)

    @patch("apps.papers.tasks.run_paper_upload_postprocess_task.apply_async")
    def test_upload_accepts_valid_csrf_token_when_checks_are_enforced(self, mocked_apply_async) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)
        client.login(username="member", password="member-password")
        pdf = SimpleUploadedFile("paper.pdf", sample_pdf_bytes(), content_type="application/pdf")

        with TemporaryDirectory() as tmpdir, override_settings(STORAGE_ROOT=Path(tmpdir)):
            response = client.post(
                "/api/papers/upload/",
                {"file": pdf, "title": "Allowed"},
                HTTP_X_CSRFTOKEN=self.csrf_token_for(client),
            )

        self.assertEqual(response.status_code, 201)
        mocked_apply_async.assert_called_once()

    def test_deep_profile_activate_rejects_missing_csrf_token_when_checks_are_enforced(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)
        client.login(username="member", password="member-password")
        paper = Paper.objects.create(title="Deep Ready", status=Paper.Status.DEEP_READY)
        profile = PaperDeepProfile.objects.create(paper=paper, version=1, is_active=True)

        response = client.post(f"/api/papers/{paper.id}/deep-profiles/{profile.id}/activate/")

        self.assertEqual(response.status_code, 403)

    def test_deep_profile_activate_accepts_valid_csrf_token_when_checks_are_enforced(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)
        client.login(username="member", password="member-password")
        paper = Paper.objects.create(title="Deep Ready", status=Paper.Status.DEEP_READY)
        PaperDeepProfile.objects.create(paper=paper, version=1, is_active=True)
        target = PaperDeepProfile.objects.create(paper=paper, version=2, is_active=False)

        response = client.post(
            f"/api/papers/{paper.id}/deep-profiles/{target.id}/activate/",
            HTTP_X_CSRFTOKEN=self.csrf_token_for(client),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active"]["id"], target.id)

    def test_deep_profile_delete_accepts_valid_csrf_token_when_checks_are_enforced(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        client = Client(enforce_csrf_checks=True)
        client.login(username="member", password="member-password")
        paper = Paper.objects.create(title="Deep Ready", status=Paper.Status.DEEP_READY)
        profile = PaperDeepProfile.objects.create(paper=paper, version=1, is_active=True)

        response = client.delete(
            f"/api/papers/{paper.id}/deep-profiles/{profile.id}/",
            HTTP_X_CSRFTOKEN=self.csrf_token_for(client),
        )

        self.assertEqual(response.status_code, 200)
