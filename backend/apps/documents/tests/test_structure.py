from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.documents.models import Document, DocumentVersion
from apps.documents.structure import build_structure
from apps.assistant.knowledge import document_chunk_source, search_knowledge, resolve_source, source_payload
from apps.assistant.reading import find_in_source, read_source, register_sources


class DocumentStructureTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='doc-structure')
        self.doc = Document.objects.create(title='Scientific notes')
        self.text = '# Method\n\n' + ('context paragraph. ' * 100) + '\n\n## Stability\n\nONLYMARK stability condition.\n\n# Limits\n\nunrelated limitation.\n'
        self.version = DocumentVersion.objects.create(document=self.doc, markdown=self.text)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_automatic_lossless_idempotent_index_and_focused_search(self):
        index = self.version.structure_indexes.get(is_current=True)
        self.assertEqual(''.join(index.chunks.values_list('text', flat=True)), self.text)
        self.assertEqual(build_structure(self.version.pk).pk, index.pk)
        rows = search_knowledge(self.user, {'content_types': ['document']}, 'ONLYMARK')
        self.assertEqual(len(rows), 1)
        self.assertIn('Method / Stability', rows[0]['title_path'])
        self.assertNotIn('context paragraph', rows[0]['excerpt'])
        self.assertEqual(search_knowledge(self.user, {'content_types': ['paper']}, 'ONLYMARK'), [])
        self.assertEqual(search_knowledge(self.user, {'document_ids': []}, 'ONLYMARK'), [])

    def test_same_section_reads_and_fixed_version_find(self):
        source = search_knowledge(self.user, {}, 'ONLYMARK')[0]
        result = read_source(self.user, {}, source, context=True, before=2, after=2)
        self.assertEqual(len(result['sources']), 1)
        self.assertNotIn('unrelated', result['sources'][0]['excerpt'])
        result = find_in_source(self.user, {}, source, query='limitation', budget=30)
        self.assertLessEqual(result['returned_chars'], 30)
        self.assertIn('Limits', result['sources'][0]['title_path'])
        self.version.is_current = False
        self.version.save(update_fields=['is_current'])
        DocumentVersion.objects.create(document=self.doc, version=2, markdown='# New\nNEWONLY')
        self.assertEqual(find_in_source(self.user, {}, source, query='NEWONLY')['sources'], [])
        self.assertEqual(search_knowledge(self.user, {}, 'ONLYMARK'), [])
        self.assertIn('ONLYMARK', resolve_source(source, self.user, {})['excerpt'])

    def test_old_citations_and_batches_survive_rebuild(self):
        source = search_knowledge(self.user, {}, 'ONLYMARK')[0]
        legacy = source_payload('document', self.version.pk, self.doc.title, self.text, 'old')
        with patch('apps.documents.structure.PARSER_VERSION', 'test-rebuild'):
            new = build_structure(self.version.pk)
        self.assertNotEqual(new.pk, source['structure_index_id'])
        self.assertEqual(resolve_source(legacy, self.user)['excerpt'], self.text)
        self.assertEqual(resolve_source(source, self.user)['chunk_id'], source['chunk_id'])
        response = self.client.get(f'/api/documents/{self.doc.pk}/', {'document_version': self.version.pk, 'structure_index': source['structure_index_id']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['structure']['id'], source['structure_index_id'])
        other = Document.objects.create(title='other')
        self.assertEqual(self.client.get(f'/api/documents/{other.pk}/', {'document_version': self.version.pk}).status_code, 404)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(f'/api/documents/{self.doc.pk}/').status_code, (401, 403))

    def test_tampering_and_scope_rejected(self):
        source = search_knowledge(self.user, {}, 'ONLYMARK')[0]
        with self.assertRaises(ValueError):
            resolve_source(source, self.user, {'content_types': ['paper']})
        with self.assertRaises(ValueError):
            resolve_source({**source, 'structure_index_id': 999}, self.user)
        DocumentVersion.objects.filter(pk=self.version.pk).update(markdown='changed')
        with self.assertRaises(ValueError):
            resolve_source(source, self.user)
        self.assertEqual(self.client.get(f'/api/documents/{self.doc.pk}/').status_code, 409)

    def test_failed_build_retains_original_and_previous_index(self):
        old = self.version.structure_indexes.get(is_current=True)
        with patch('apps.documents.structure.PARSER_VERSION', 'failure'), patch('apps.documents.structure.split_markdown', side_effect=ValueError('bad')):
            with self.assertRaises(ValueError):
                build_structure(self.version.pk)
        self.assertEqual(self.version.structure_indexes.get(is_current=True).pk, old.pk)
        with patch('apps.documents.signals.build_structure', side_effect=ValueError('bad')):
            plain = DocumentVersion.objects.create(document=self.doc, version=2, markdown='FALLBACKWORD')
        self.assertEqual(DocumentVersion.objects.get(pk=plain.pk).markdown, 'FALLBACKWORD')
        self.assertNotIn('chunk_id', search_knowledge(self.user, {}, 'FALLBACKWORD')[0])

    def test_command_default_read_only_and_explicit_apply(self):
        self.version.structure_indexes.all().delete()
        output = StringIO()
        call_command('index_documents', '--document-version', str(self.version.pk), stdout=output)
        self.assertFalse(self.version.structure_indexes.exists())
        call_command('index_documents', '--document-version', str(self.version.pk), '--apply', stdout=output)
        self.assertEqual(self.version.structure_indexes.count(), 1)

    def test_registry_keeps_different_document_chunks(self):
        sources = [document_chunk_source(c) for c in self.version.structure_indexes.get(is_current=True).chunks.select_related('index__version__document')]
        registry = {}
        emitted, _, _ = register_sources(registry, sources, 18000)
        self.assertEqual(len(emitted), len(sources))
        self.assertEqual(len(registry), len(sources))
