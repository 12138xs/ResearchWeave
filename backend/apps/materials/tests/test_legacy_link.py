from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from apps.materials.models import Material, MaterialVersion
from apps.materials.services import ingest, parse_version
from apps.papers.models import Paper
from apps.papers.services.delete import delete_paper


class LegacyLinkTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        setting = override_settings(STORAGE_ROOT=self.temp.name)
        setting.enable()
        self.addCleanup(setting.disable)
        self.owner = get_user_model().objects.create_user(username='curator', is_staff=True)
        self.client.force_login(self.owner)
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        stream = BytesIO()
        writer.write(stream)
        self.pdf = stream.getvalue()

    def paper(self, key='objects/pdf/original.pdf', content=None):
        if key:
            path = Path(self.temp.name) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.pdf if content is None else content)
        return Paper.objects.create(title='公开论文', abstract='仅摘要', source_pdf_path=key)

    def run_link(self, apply=False):
        out = StringIO()
        call_command('link_legacy_papers', owner=self.owner.username, apply=apply, stdout=out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_dry_run_and_missing_are_read_only(self):
        self.paper()
        self.paper('')
        missing = self.paper('objects/pdf/missing.pdf')
        (Path(self.temp.name) / missing.source_pdf_path).unlink()
        rows = self.run_link()
        self.assertEqual({r['status'] for r in rows}, {'available', 'abstract_only', 'missing_file'})
        self.assertFalse(Material.objects.exists())
        self.run_link(True)
        self.assertEqual(Material.objects.count(), 1)

    def test_idempotent_duplicate_preserves_original_and_fixed_reference(self):
        first = self.paper()
        second = self.paper('objects/pdf/copy.pdf')
        self.run_link(True)
        self.run_link(True)
        self.assertEqual(MaterialVersion.objects.count(), 1)
        version = MaterialVersion.objects.get()
        self.assertEqual(version.legacy_links.count(), 2)
        self.assertEqual(version.material.source_kind, 'paper_fulltext')
        parse_version(version.pk)
        self.assertEqual(version.evidence.count(), 1)
        delete_paper(first)
        response = self.client.get(f'/api/materials/{version.material_id}/versions/{version.pk}/file/')
        self.assertEqual(b''.join(response.streaming_content), self.pdf)
        self.assertTrue(Paper.objects.filter(pk=second.pk).exists())

    def test_changed_original_creates_new_version_and_preserves_old(self):
        paper = self.paper()
        self.run_link(True)
        old = MaterialVersion.objects.get()
        path = Path(self.temp.name) / paper.source_pdf_path
        path.write_bytes(self.pdf + b'\n% revised\n')
        self.run_link(True)
        self.assertEqual(Material.objects.count(), 1)
        self.assertEqual(MaterialVersion.objects.count(), 2)
        self.assertEqual((Path(self.temp.name) / old.storage_key).read_bytes(), self.pdf)

    def test_parse_failure_is_reported_without_fulltext_claim(self):
        self.paper(content=b'not a PDF')
        rows = self.run_link(True)
        self.assertEqual(rows[0]['status'], 'parse_failed')
        version = MaterialVersion.objects.get()
        data = self.client.get(f'/api/materials/{version.material_id}/').json()
        self.assertEqual(data['versions'][0]['retrieval_status'], 'unavailable')

    def test_classification_is_explicit_and_does_not_relabel_duplicate(self):
        version, _ = ingest(SimpleUploadedFile('card.md', b'PDE notes'), owner=self.owner,
                            source_kind='derived_research_card')
        duplicate, created = ingest(SimpleUploadedFile('paper.md', b'PDE notes'), owner=self.owner,
                                    source_kind='paper_fulltext')
        self.assertFalse(created)
        self.assertEqual(duplicate.material.source_kind, 'derived_research_card')
        self.assertEqual(version.material.source_kind, 'derived_research_card')
        raw, _ = ingest(SimpleUploadedFile('paper.pdf', self.pdf), owner=self.owner)
        self.assertEqual(raw.material.source_kind, 'unclassified')

    def test_whitespace_is_not_searchable_and_private_metadata_is_hidden(self):
        version, _ = ingest(SimpleUploadedFile('blank.md', b' \n'), owner=self.owner, visibility='private')
        parse_version(version.pk)
        data = self.client.get(f'/api/materials/{version.material_id}/').json()
        self.assertEqual(data['versions'][0]['retrieval_status'], 'no_text')
        other = get_user_model().objects.create_user(username='other')
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/api/materials/{version.material_id}/').status_code, 404)
