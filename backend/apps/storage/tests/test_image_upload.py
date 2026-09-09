from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings


class ImageUploadTests(TestCase):
    def login_member(self) -> None:
        get_user_model().objects.create_user(username="member", password="member-password")
        self.client.login(username="member", password="member-password")

    def test_uploads_image_and_returns_markdown_url(self) -> None:
        self.login_member()
        with TemporaryDirectory() as tmpdir:
            image = SimpleUploadedFile(
                "plot.png",
                b"\x89PNG\r\n\x1a\nfakepng",
                content_type="image/png",
            )

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.post("/api/storage/upload-image/", {"image": image})

            self.assertEqual(response.status_code, 201)
            payload = response.json()
            self.assertEqual(payload["markdown"], f"![plot]({payload['url']})")
            self.assertTrue(payload["url"].startswith("/api/assets/images/"))
            self.assertTrue((Path(tmpdir) / payload["storage_key"]).exists())
            self.assertNotIn("..", payload["storage_key"])

    def test_rejects_non_image_upload(self) -> None:
        self.login_member()
        text = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")

        response = self.client.post("/api/storage/upload-image/", {"image": text})

        self.assertEqual(response.status_code, 400)
        self.assertIn("image", response.json())

    def test_serves_uploaded_image(self) -> None:
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "objects/images/example.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")

            with override_settings(STORAGE_ROOT=Path(tmpdir)):
                response = self.client.get("/api/assets/images/example.png")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(b"".join(response.streaming_content), image_path.read_bytes())
