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

    def test_frontmatter_is_not_a_section_heading(self):
        text = '---\ntitle: Metadata\nauthor: Example\n---\n\n# Real section\nbody'
        sections, chunks = split_markdown(text)
        self.assertEqual([s['title'] for s in sections], ['Real section'])
        self.assertEqual(''.join(c['text'] for c in chunks), text)

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
        self.assertIn(f'structure_index={old.pk}', row['url'])
        self.client.force_login(self.user)
        response = self.client.get(f'/api/materials/{self.material.pk}/versions/{self.version.pk}/?structure_index={old.pk}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['structure']['id'], old.pk)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/api/materials/{self.material.pk}/versions/{self.version.pk}/?structure_index={old.pk}').status_code, 404)
        self.assertEqual(self.version.structure_indexes.filter(is_current=True).count(), 1)

    def test_tampering_with_original_evidence_invalidates_chunk(self):
        build_structure(self.version.pk)
        row = search_knowledge(self.user, {}, 'numerical stability')[0]
        Evidence.objects.filter(pk=row['id']).update(text='changed')
        self.assertFalse(source_allowed(row, self.user))

    def test_pdf_and_structured_candidates_share_relevance_budget(self):
        for number in range(9):
            m = Material.objects.create(owner=self.user, title='weak', content_type='paper')
            v = MaterialVersion.objects.create(material=m, number=1, sha256=str(number)*64,
                filename='weak.md', format='md', status='ready', size=20, created_by=self.user)
            Evidence.objects.create(version=v, ordinal=1, line_start=1, line_end=1, text='PINN weak')
            build_structure(v.pk)
        m = Material.objects.create(owner=self.user, title='PINN inverse coefficient identification', content_type='paper')
        v = MaterialVersion.objects.create(material=m, number=1, sha256='f'*64,
            filename='strong.pdf', format='pdf', status='ready', size=20, created_by=self.user)
        e = Evidence.objects.create(version=v, ordinal=1, page=1, text='PINN inverse coefficient identification')
        rows = search_knowledge(self.user, {}, 'PINN inverse coefficient identification')
        self.assertEqual(rows[0]['id'], e.pk)
        self.assertNotIn('chunk_id', rows[0])

    def test_command_dry_run_and_explicit_version_build(self):
        from django.core.management import call_command
        from io import StringIO
        call_command('index_materials', stdout=StringIO())
        self.assertFalse(self.version.structure_indexes.exists())
        call_command('index_materials', '--apply', '--material-version', str(self.version.pk), stdout=StringIO())
        self.assertEqual(self.version.structure_indexes.count(), 1)
