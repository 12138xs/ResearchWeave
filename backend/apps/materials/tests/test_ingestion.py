from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from io import BytesIO, StringIO
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.core.management import call_command, CommandError
from django.db import close_old_connections
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
        evidence = version.evidence.first()
        url = f"/api/materials/{version.material_id}/versions/{version.pk}/evidence/{evidence.pk}/review/"
        self.assertEqual(self.client.post(url, {"confirmed": True}, content_type="application/json").status_code, 400)

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

    def test_review_requires_owner_and_explicit_confirmation(self):
        version, _ = self.upload(body="核对样例：\ufffd".encode())
        parse_version(version.pk)
        evidence = version.evidence.get()
        url = f"/api/materials/{version.material_id}/versions/{version.pk}/evidence/{evidence.pk}/review/"
        self.assertEqual(self.client.post(url, {}, content_type="application/json").status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {"confirmed": True}, content_type="application/json").status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url, {"confirmed": True}, content_type="application/json").status_code, 200)
        evidence.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(evidence.reviewed_by, self.owner)
        self.assertIsNotNone(evidence.reviewed_at)
        self.assertFalse(evidence.review_required)
        self.assertEqual(version.status, "ready")

    def test_batch_partial_failure_and_repeat_preserve_success(self):
        valid = Path(self.temp.name) / "valid.md"
        invalid = Path(self.temp.name) / "invalid.txt"
        valid.write_text("# 批量材料\n证据", encoding="utf-8")
        invalid.write_text("错误格式", encoding="utf-8")
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("ingest_materials", str(valid), str(invalid), owner=self.owner.username, parse=True, stdout=output)
        self.assertEqual(Material.objects.count(), 1)
        self.assertEqual(MaterialVersion.objects.get().status, "ready")
        call_command("ingest_materials", str(valid), owner=self.owner.username, parse=True, stdout=output)
        self.assertEqual(MaterialVersion.objects.count(), 1)
        self.assertEqual(Evidence.objects.count(), 1)

    def test_stale_queue_retry_and_completed_evidence_not_reparsed(self):
        from datetime import timedelta
        from django.utils import timezone
        version, _ = self.upload()
        url = f"/api/materials/{version.material_id}/versions/{version.pk}/retry/"
        self.assertEqual(self.client.post(url).status_code, 409)
        MaterialVersion.objects.filter(pk=version.pk).update(updated_at=timezone.now() - timedelta(minutes=6))
        with patch("apps.materials.tasks.parse_material.apply_async") as queued:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.post(url).status_code, 202)
            queued.assert_called_once()
        parse_version(version.pk)
        with patch("apps.materials.services._extract") as extract:
            parse_version(version.pk)
            extract.assert_not_called()
        self.assertEqual(self.client.post(url).status_code, 200)

    def test_tampered_original_fails_before_creating_evidence(self):
        version, _ = self.upload()
        (Path(self.temp.name) / version.storage_key).write_bytes(b"Tampered")
        parse_version(version.pk)
        version.refresh_from_db()
        self.assertEqual(version.status, "failed")
        self.assertEqual(version.evidence.count(), 0)

    def test_evidence_write_failure_is_atomic_and_can_recover(self):
        from django.db import DatabaseError
        version, _ = self.upload()
        with patch("apps.materials.services.Evidence.objects.bulk_create", side_effect=DatabaseError("write failed")):
            parse_version(version.pk)
        version.refresh_from_db()
        self.assertEqual(version.status, "failed")
        self.assertEqual(version.evidence.count(), 0)
        parse_version(version.pk)
        version.refresh_from_db()
        self.assertEqual(version.status, "ready")
        self.assertEqual(version.evidence.count(), 1)


class ConcurrentIngestionTests(TransactionTestCase):
    def test_identical_parallel_uploads_create_one_original(self):
        owner = get_user_model().objects.create_user(username="parallel-owner")
        with TemporaryDirectory() as temp, override_settings(STORAGE_ROOT=temp):
            def upload(_):
                close_old_connections()
                try:
                    return ingest(SimpleUploadedFile("same.md", b"Concurrent evidence"), owner=owner)[0].pk
                finally:
                    close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:
                ids = list(pool.map(upload, range(2)))
            self.assertEqual(ids[0], ids[1])
            self.assertEqual(Material.objects.count(), 1)
            self.assertEqual(len(list(Path(temp).rglob("*.md"))), 1)
