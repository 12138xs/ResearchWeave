from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from apps.materials.models import Material, MaterialVersion, Evidence
from apps.materials.structure import split_markdown, build_structure, verified_chunk_text
from apps.assistant.knowledge import material_source, search_knowledge, resolve_source, source_allowed
from apps.assistant.reading import read_source, find_in_source


class MarkdownStructureTests(SimpleTestCase):
    def test_ast_headings_and_atomic_blocks_preserve_every_character(self):
        text = '# Method\n\nintro\n\n## Solver\n\n```python\n# not heading\n' + 'code\n' * 400 + '```\n\n$$\n# not math heading\n\nx=1\n$$\n\n|a|b|\n|-|-|\n|1|2|\n\nConclusion\n==========\nend'
        sections, chunks = split_markdown(text)
        self.assertEqual([s['title'] for s in sections], ['Method', 'Solver', 'Conclusion'])
        self.assertEqual(sections[1]['parent'], 1)
        self.assertEqual(''.join(c['text'] for c in chunks), text)
        self.assertTrue(any('```python' in c['text'] and c['text'].count('```') == 2 and c['oversized'] for c in chunks))
        self.assertTrue(any('$$\n# not math heading\n\nx=1\n$$' in c['text'] for c in chunks))
        self.assertTrue(any('|a|b|\n|-|-|\n|1|2|' in c['text'] for c in chunks))

    def test_unclosed_math_and_no_headings_do_not_drop_content(self):
        for text in ['', '\n\n', 'paragraph', '$$\n# not a heading\n\nmore', r'\[' + '\n# math\n\nx\n' + r'\]']:
            sections, chunks = split_markdown(text)
            self.assertEqual(sections, [])
            self.assertEqual(''.join(c['text'] for c in chunks), text)


class StructureIndexTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='structure-owner')
        self.other = get_user_model().objects.create_user(username='structure-other')
        self.material = Material.objects.create(owner=self.user, title='Synthetic', content_type='paper', visibility='private')
        self.version = MaterialVersion.objects.create(material=self.material, number=1, sha256='a'*64,
            filename='synthetic.md', format='md', status='ready', size=1000, created_by=self.user)
        text = '# Method\n\n' + '\n'.join('setup' for _ in range(65)) + '\n\n## Solver\n\nPINN numerical stability\n\n## Limits\n\nPINN requires conditions'
        lines = text.splitlines()
        for start in range(0, len(lines), 60):
            Evidence.objects.create(version=self.version, ordinal=start // 60 + 1,
                line_start=start + 1, line_end=min(start + 60, len(lines)), text='\n'.join(lines[start:start+60]))
        self.old = material_source(self.version.evidence.first())

    def test_cross_evidence_chunks_are_traceable_and_old_citations_survive(self):
        before = list(self.version.evidence.values())
        index = build_structure(self.version.pk)
        self.assertEqual(build_structure(self.version.pk).pk, index.pk)
        self.assertEqual(list(self.version.evidence.values()), before)
        self.assertTrue(source_allowed(self.old, self.user))
        self.assertTrue(any(len(c.evidence_ids) > 1 for c in index.chunks.all()))
        for chunk in index.chunks.all():
            self.assertEqual(verified_chunk_text(chunk), chunk.text)
        rows = search_knowledge(self.user, {'content_types':['paper']}, 'numerical stability')
        self.assertTrue(rows)
        self.assertIn('chunk_id', rows[0])
        self.assertIn('Solver', rows[0]['location'])
        self.assertEqual(resolve_source(rows[0], self.user)['excerpt'], rows[0]['excerpt'])
        result = find_in_source(self.user, {'content_types':['paper']}, rows[0], query='requires conditions')
        self.assertIn('Limits', result['sources'][0]['location'])

    def test_context_is_same_section_and_reclassification_still_blocks(self):
        build_structure(self.version.pk)
        row = search_knowledge(self.user, {}, 'numerical stability')[0]
        output = read_source(self.user, {}, row, context=True, before=2, after=2)
        self.assertTrue(all('Solver' in s['location'] for s in output['sources']))
        self.assertEqual(search_knowledge(self.other, {}, 'numerical stability'), [])
        self.material.internal_ai_blocked = True; self.material.save()
        self.assertFalse(source_allowed(row, self.user))
        self.assertEqual(search_knowledge(self.user, {}, 'numerical stability'), [])

    def test_failed_rebuild_keeps_old_index_and_old_generation_can_be_read(self):
        old = build_structure(self.version.pk)
        row = search_knowledge(self.user, {}, 'numerical stability')[0]
        with patch('apps.materials.structure.PARSER_VERSION', 'next'), patch('apps.materials.structure.split_markdown', side_effect=ValueError('failure')):
            with self.assertRaises(ValueError): build_structure(self.version.pk)
        old.refresh_from_db(); self.assertTrue(old.is_current)
        with patch('apps.materials.structure.PARSER_VERSION', 'next'):
            new = build_structure(self.version.pk)
        self.assertNotEqual(old.pk, new.pk)
        self.assertTrue(source_allowed(row, self.user))
        self.assertEqual(self.version.structure_indexes.filter(is_current=True).count(), 1)

    def test_tampering_with_original_evidence_invalidates_chunk(self):
        build_structure(self.version.pk)
        row = search_knowledge(self.user, {}, 'numerical stability')[0]
        Evidence.objects.filter(pk=row['id']).update(text='changed')
        self.assertFalse(source_allowed(row, self.user))
