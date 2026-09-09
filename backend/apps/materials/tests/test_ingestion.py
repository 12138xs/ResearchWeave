from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from apps.materials.models import Material, MaterialVersion, Evidence
from apps.materials.services import ingest, parse_version


class IngestionTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = override_settings(STORAGE_ROOT=self.temp.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.owner = get_user_model().objects.create_user(username="owner")
        self.other = get_user_model().objects.create_user(username="other")
        self.client.force_login(self.owner)

    def upload(self, body=b"# PDE\n\nConvergence evidence.\n", name="notes.md", **kwargs):
        return ingest(SimpleUploadedFile(name, body), owner=self.owner, **kwargs)

    def test_markdown_original_dedup_and_line_evidence(self):
        version, created = self.upload()
        duplicate, again = self.upload()
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(version.pk, duplicate.pk)
        parse_version(version.pk)
        parse_version(version.pk)
        version.refresh_from_db()
        self.assertEqual(version.status, "ready")
        self.assertEqual(version.evidence.count(), 1)
        evidence = version.evidence.get()
        self.assertEqual((evidence.line_start, evidence.line_end), (1, 3))
        self.assertIn("Convergence", evidence.text)
        response = self.client.get(f"/api/materials/{version.material_id}/versions/{version.pk}/file/")
        self.assertEqual(b"".join(response.streaming_content), b"# PDE\n\nConvergence evidence.\n")
        self.assertIn("no-store", response["Cache-Control"])

    def test_versions_keep_old_evidence_and_reject_cross_material_urls(self):
        old, _ = self.upload()
        parse_version(old.pk)
        new, _ = self.upload(body=b"New results", material=old.material)
        parse_version(new.pk)
        old.refresh_from_db()
        self.assertEqual((old.number, new.number), (1, 2))
        self.assertEqual(old.evidence.count(), 1)
        another, _ = self.upload(body=b"Another document")
        self.assertEqual(self.client.get(f"/api/materials/{another.material_id}/versions/{old.pk}/file/").status_code, 404)

    def test_private_dedup_and_all_read_paths_respect_owner(self):
        version, _ = self.upload(visibility="private")
        parse_version(version.pk)
        self.client.force_login(self.other)
        for suffix in ["", f"versions/{version.pk}/", f"versions/{version.pk}/file/"]:
            self.assertEqual(self.client.get(f"/api/materials/{version.material_id}/{suffix}").status_code, 404)
        self.assertEqual(self.client.get("/api/materials/").json()["count"], 0)
        other_version, created = ingest(SimpleUploadedFile("notes.md", b"# PDE\n\nConvergence evidence.\n"), owner=self.other, visibility="private")
        self.assertTrue(created)
        self.assertNotEqual(version.pk, other_version.pk)
        self.client.logout()
        self.assertIn(self.client.get("/api/materials/").status_code, (401, 403))

    def test_team_dedup_does_not_transfer_edit_rights(self):
        version, _ = self.upload(visibility="team")
        self.client.force_login(self.other)
        response = self.client.post(f"/api/materials/{version.material_id}/versions/", {"file": SimpleUploadedFile("new.md", b"Changed")})
        self.assertEqual(response.status_code, 404)
        duplicate, created = ingest(SimpleUploadedFile("same.md", b"# PDE\n\nConvergence evidence.\n"), owner=self.other, visibility="team")
        self.assertFalse(created)
        self.assertEqual(duplicate.pk, version.pk)
        version.material.refresh_from_db()
        self.assertEqual(version.material.owner_id, self.owner.pk)

    def test_pdf_blank_pages_preserved_and_marked_for_review(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)
        data = BytesIO()
        writer.write(data)
        version, _ = self.upload(data.getvalue(), "scan.pdf")
        parse_version(version.pk)
        version.refresh_from_db()
        self.assertEqual(version.status, "needs_review")
        self.assertEqual(list(version.evidence.values_list("page", flat=True)), [1, 2])
        self.assertTrue(all(row.review_required for row in version.evidence.all()))

    def test_invalid_utf8_and_corrupt_pdf_fail_visibly_without_partial_evidence(self):
        for body, name in [(b"\xff\xfe", "bad.md"), (b"%PDF-broken", "bad.pdf")]:
            version, _ = self.upload(body, name)
            parse_version(version.pk)
            version.refresh_from_db()
            self.assertEqual(version.status, "failed")
            self.assertTrue(version.error)
            self.assertEqual(version.evidence.count(), 0)
            self.assertEqual(version.task.status, "failed")

    @patch("apps.materials.tasks.parse_material.apply_async", side_effect=RuntimeError("secret broker address"))
    def test_queue_failure_is_visible_and_retryable(self, queue):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/materials/", {"file": SimpleUploadedFile("notes.md", b"Evidence")})
        self.assertEqual(response.status_code, 201)
        version = MaterialVersion.objects.get()
        self.assertEqual(version.status, "failed")
        self.assertNotIn("secret", version.error)
        with patch("apps.materials.tasks.parse_material.apply_async") as retry:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(f"/api/materials/{version.material_id}/versions/{version.pk}/retry/")
            self.assertEqual(response.status_code, 202)
            retry.assert_called_once()

    def test_file_validation_leaves_no_rows_or_files(self):
        response = self.client.post("/api/materials/", {"file": SimpleUploadedFile("bad.exe", b"bad")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Material.objects.count(), 0)
        self.assertEqual(list(Path(self.temp.name).rglob("*.exe")), [])

    def test_card_requires_evidence_from_exact_version(self):
        version, _ = self.upload()
        parse_version(version.pk)
        another, _ = self.upload(body=b"Other source")
        parse_version(another.pk)
        url = f"/api/materials/{version.material_id}/versions/{version.pk}/cards/"
        bad = {"title": "研究卡片", "markdown": "主张", "evidence_ids": [another.evidence.get().pk]}
        self.assertEqual(self.client.post(url, bad, content_type="application/json").status_code, 400)
        good = {**bad, "evidence_ids": [version.evidence.get().pk]}
        self.assertEqual(self.client.post(url, good, content_type="application/json").status_code, 201)
        self.assertEqual(self.client.post(url, good, content_type="application/json").status_code, 200)
        self.assertEqual(version.cards.count(), 1)
        self.assertEqual(Evidence.objects.count(), 2)
