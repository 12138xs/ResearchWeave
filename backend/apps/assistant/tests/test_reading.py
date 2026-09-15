import json
import uuid
import os
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.assistant.knowledge import search_knowledge
from apps.assistant.models import AssistantExchange, AssistantSession
from apps.assistant.agent import run_exchange
from apps.assistant.tests.test_agent import reply, search
from apps.materials.models import Material, MaterialVersion, Evidence


class ReadingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='reading-owner')
        self.other = get_user_model().objects.create_user(username='reading-other')
        self.material = Material.objects.create(title='geometry operator', owner=self.user, visibility='private', source_kind='paper_fulltext')
        self.version = MaterialVersion.objects.create(material=self.material, number=1, sha256='a'*64,
            filename='paper.pdf', format='pdf', size=100, status='needs_review', created_by=self.user)
        self.first = Evidence.objects.create(version=self.version, ordinal=1, page=1, text='geometry '+ 'background '*100 + 'LIMITATION_END')
        self.second = Evidence.objects.create(version=self.version, ordinal=2, page=2, text='Topology restriction: regular topology only.')

    def source(self):
        return search_knowledge(self.user, {}, 'geometry')[0]

    def test_find_in_source_reaches_distant_evidence_without_switching_version(self):
        from apps.assistant.reading import find_in_source
        source = self.source()
        Evidence.objects.create(version=self.version, ordinal=17, page=17, text='topology appendix: decomposition is future work')
        new = MaterialVersion.objects.create(material=self.material, number=2, sha256='b'*64,
            filename='paper.pdf', format='pdf', size=100, status='ready', created_by=self.user)
        Evidence.objects.create(version=new, ordinal=17, page=17, text='topology appendix NEW VERSION')
        result = find_in_source(self.user, {}, source, query='appendix decomposition', budget=50)
        self.assertEqual(result['sources'][0]['page'], 17)
        self.assertTrue(all(row['version_id'] == self.version.pk for row in result['sources']))
        self.assertLessEqual(sum(len(row['excerpt']) for row in result['sources']), 50)

    def test_find_in_source_checks_permissions_scope_and_parameters(self):
        from apps.assistant.reading import find_in_source
        source = self.source()
        for user, scope, query in [(self.other, {}, 'topology'), (self.user, {'material_ids': []}, 'topology'),
                                   (self.user, {}, ''), (self.user, {}, ['topology'])]:
            with self.assertRaises(ValueError):
                find_in_source(user, scope, source, query=query)

    @patch('apps.assistant.agent.call_minimax_chat')
    def test_agent_finds_distant_evidence_within_shared_tool_budget(self, model):
        Evidence.objects.create(version=self.version, ordinal=17, page=17, text='decomposition future work')
        session = AssistantSession.objects.create(created_by=self.user, title='geometry')
        row = AssistantExchange.objects.create(session=session, question='geometry limitations', status='queued', request_id=uuid.uuid4())
        model.side_effect = [search('geometry'), reply(calls=[{'id': 'find-1', 'type': 'function', 'function': {
            'name': 'find_in_source', 'arguments': json.dumps({'source_ref': 'S1', 'query': 'decomposition', 'budget': 100})}}]),
            reply({'answer': '域分解是未来工作 [S3]。'}), reply({'answer': '域分解是未来工作 [S3]。'})]
        run_exchange(row.pk, 1)
        row.refresh_from_db()
        self.assertEqual(row.status, 'completed')
        self.assertEqual(row.sources[0]['page'], 17)
        self.assertEqual(row.usage['tool_calls'], 2)
        self.assertEqual(row.usage['read_calls'], 1)
        self.assertEqual(row.usage['find_calls'], 1)
        self.assertLessEqual(row.usage['evidence_chars'], 18000)

    def test_read_beyond_excerpt_and_fixed_version_context(self):
        from apps.assistant.reading import read_source
        source = self.source()
        self.assertNotIn('LIMITATION_END', source['excerpt'])
        result = read_source(self.user, {}, source, budget=3000)
        self.assertIn('LIMITATION_END', result['sources'][0]['excerpt'])
        new = MaterialVersion.objects.create(material=self.material, number=2, sha256='b'*64,
            filename='paper.pdf', format='pdf', size=100, status='ready', created_by=self.user)
        Evidence.objects.create(version=new, ordinal=2, page=2, text='NEW VERSION must not replace old')
        context = read_source(self.user, {}, source, budget=3000, context=True, after=1)
        self.assertEqual([r['page'] for r in context['sources']], [1, 2])
        self.assertIn('regular topology', context['sources'][1]['excerpt'])
        self.assertTrue(all(r['version_id'] == self.version.pk for r in context['sources']))

    def test_scope_permission_hash_and_budget_are_enforced(self):
        from apps.assistant.reading import read_source
        source = self.source()
        for user, scope, modified, budget in [
            (self.other, {}, source, 100),
            (self.user, {'material_ids': []}, source, 100),
            (self.user, {}, {**source, 'version_id': 999}, 100),
            (self.user, {}, source, 3001),
            (self.user, {}, source, True),
        ]:
            with self.assertRaises(ValueError):
                read_source(user, scope, modified, budget=budget)
        result = read_source(self.user, {}, source, budget=50)
        self.assertEqual(sum(len(r['excerpt']) for r in result['sources']), 50)
        self.assertTrue(result['truncated'])
        self.first.text = 'changed body'
        self.first.save()
        with self.assertRaises(ValueError):
            read_source(self.user, {}, source)

    def test_query_fusion_and_duplicate_files_do_not_crowd_out_sources(self):
        duplicate = Material.objects.create(title='geometry operator copy', owner=self.user, visibility='team')
        version = MaterialVersion.objects.create(material=duplicate, number=1, sha256=self.version.sha256,
            filename='copy.pdf', format='pdf', size=100, status='ready', created_by=self.user)
        Evidence.objects.create(version=version, ordinal=1, text=self.first.text)
        rows = search_knowledge(self.user, {}, '不存在术语', queries=['geometry', 'topology'])
        self.assertEqual(len([r for r in rows if r['version_sha256'] == self.version.sha256 and r['ordinal'] == 1]), 1)
        self.assertTrue(any('regular topology' in r['excerpt'] for r in rows))

    @patch('apps.assistant.agent.call_minimax_chat')
    def test_agent_search_read_context_and_publish_actual_evidence(self, model):
        session = AssistantSession.objects.create(created_by=self.user, scope_json={})
        exchange = AssistantExchange.objects.create(session=session, question='geometry 限制是什么', status='queued', request_id=uuid.uuid4())
        calls = [{'id': 'read-1', 'type': 'function', 'function': {'name': 'read_context',
                  'arguments': json.dumps({'source_ref': 'S1', 'after': 1, 'budget': 3000})}}]
        def respond(messages, **kwargs):
            if model.call_count == 1:
                return search('geometry')
            if model.call_count == 2:
                return reply(calls=calls)
            if model.call_count == 3:
                return reply({'answer': '依据已读取。'})
            sources = json.loads(messages[-1]['content'])['sources']
            source = next(r for r in sources if 'regular topology' in r['excerpt'])
            return reply({'answer': '拓扑存在限制 [' + source['label'] + ']。'})
        model.side_effect = respond
        run_exchange(exchange.pk, 1)
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, 'completed', exchange.usage)
        self.assertEqual(exchange.usage['read_calls'], 1)
        self.assertLessEqual(exchange.usage['evidence_chars'], 18000)
        self.assertTrue(any('regular topology' in row['excerpt'] for row in exchange.sources))
        self.assertTrue(any(row.get('page') == 2 for row in exchange.sources))

    def test_global_budget_counts_repeated_outputs_and_keeps_citations_immutable(self):
        from apps.assistant.reading import register_sources
        from apps.assistant.knowledge import source_payload
        registry = {}
        rows = [source_payload('document', i, '测试', 'x'*600, '固定版本') for i in range(1, 9)]
        used = 0
        for _ in range(6):
            output, charged, limited = register_sources(registry, rows, 18000-used)
            used += charged
            self.assertEqual(charged, sum(len(row['excerpt']) for row in output))
            self.assertLessEqual(used, 18000)
        self.assertEqual(used, 18000)
        self.assertEqual(registry['S1']['excerpt'], 'x'*600)

    def test_read_context_accepts_structured_document_but_rejects_legacy_and_path(self):
        from apps.assistant.reading import read_source
        from apps.documents.models import Document, DocumentVersion
        doc = Document.objects.create(title='geometry document')
        version = DocumentVersion.objects.create(document=doc, markdown='geometry '+ 'data '*300)
        source = next(row for row in search_knowledge(self.user, {'document_ids': [doc.pk]}, 'geometry') if row['id'] == version.pk)
        self.assertGreater(len(read_source(self.user, {}, source)['sources'][0]['excerpt']), 600)
        self.assertTrue(read_source(self.user, {}, source, context=True)['sources'])
        from apps.assistant.knowledge import source_payload
        legacy = source_payload('document', version.pk, doc.title, version.markdown, 'legacy')
        with self.assertRaises(ValueError):
            read_source(self.user, {}, legacy, context=True)
        with self.assertRaises(ValueError):
            read_source(self.user, {}, {'type': 'path', 'id': '/etc/passwd'})

    @patch('apps.assistant.agent.call_minimax_chat')
    def test_revocation_before_read_stops_further_transmission(self, model):
        session = AssistantSession.objects.create(created_by=self.user, scope_json={})
        exchange = AssistantExchange.objects.create(session=session, question='geometry', status='queued', request_id=uuid.uuid4())
        def respond(*args, **kwargs):
            if model.call_count == 1:
                return search('geometry')
            self.material.owner = self.other
            self.material.save()
            return reply(calls=[{'id': 'read', 'type': 'function', 'function': {'name': 'read_evidence', 'arguments': '{"source_ref":"S1"}'}}])
        model.side_effect = respond
        run_exchange(exchange.pk, 1)
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, 'failed')
        self.assertEqual(model.call_count, 2)
        self.assertEqual(exchange.answer, '')

    def test_discovery_reserves_capacity_for_later_read_fragments(self):
        from apps.assistant.reading import register_sources
        from apps.assistant.knowledge import source_payload
        registry = {}
        rows = [source_payload('document', i, '检索', 'short', '固定版本') for i in range(1, 17)]
        _, _, limited = register_sources(registry, rows, 18000, max_sources=10)
        self.assertTrue(limited)
        self.assertEqual(len(registry), 10)
        output, _, _ = register_sources(registry, [source_payload('document', 1, '补读', 'longer complete evidence', '固定版本')], 17000)
        self.assertEqual(output[0]['label'], 'S11')
        self.assertEqual(registry['S1']['excerpt'], 'short')

    def test_shared_ranking_and_linked_paper_scope(self):
        from apps.search.evidence import search_evidence
        from apps.materials.models import LegacyPaperLink
        from apps.papers.models import Paper
        paper = Paper.objects.create(title='geometry paper', abstract='geometry abstract')
        LegacyPaperLink.objects.create(paper=paper, version=self.version, original_sha256=self.version.sha256)
        rows = search_knowledge(self.user, {'paper_ids': [paper.pk]}, 'geometry')
        self.assertTrue(any(row['type'] == 'material' for row in rows))
        other_rows = search_knowledge(self.other, {'paper_ids': [paper.pk]}, 'geometry')
        self.assertFalse(any(row['type'] == 'material' for row in other_rows))
        api_rows = search_evidence(self.user, {'q': 'geometry', 'limit': 8})['results']
        agent_rows = search_knowledge(self.user, {'material_ids': [self.material.pk]}, 'geometry')
        self.assertEqual([row['evidence_id'] for row in api_rows], [row['id'] for row in agent_rows])

    def test_query_and_neighbor_bounds_are_not_advisory(self):
        from apps.assistant.reading import read_source
        source = self.source()
        with self.assertRaises(ValueError):
            search_knowledge(self.user, {}, 'geometry', queries=['a', 'b', 'c'])
        with self.assertRaises(ValueError):
            search_knowledge(self.user, {}, 'geometry', queries=[123])
        with self.assertRaises(ValueError):
            read_source(self.user, {}, source, context=True, after=3)
        with self.assertRaises(ValueError):
            read_source(self.user, {}, source, offset=source['total_chars']+1)

    def test_whitespace_only_page_is_not_a_search_candidate(self):
        from apps.search.evidence import search_evidence
        self.first.text = ' \n\t'
        self.first.save()
        self.assertNotIn(self.first.pk, [row['id'] for row in search_knowledge(self.user, {}, 'geometry')])
        self.assertNotIn(self.first.pk, [row['evidence_id'] for row in search_evidence(self.user, {'q': 'geometry'})['results']])


@skipUnless(os.getenv("RWV_M6C_LIVE") == "1", "需显式启用服务器冻结代表题")
class FrozenReadingTests(TestCase):
    def test_frozen_geometry_read_loop(self):
        import hashlib
        from apps.assistant.tests.test_full_library_qa import validate_dataset, seed_dataset, measure_case
        self.assertTrue(os.environ.get("POSTGRES_DB", "").startswith("rwv_m6c_"))
        raw = Path(os.environ["RWV_BASELINE_DATASET"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), os.environ["RWV_BASELINE_SHA256"])
        data = validate_dataset(json.loads(raw))
        user = get_user_model().objects.create_user(username="reading-live-self")
        other = get_user_model().objects.create_user(username="reading-live-other")
        refs = seed_dataset(data, user, other)
        case = next(case for case in data["cases"] if case["id"] == "geometry")
        self.assertEqual(case["split"], "baseline")
        result = measure_case(case, refs, user)
        result.update(commit=os.environ["RWV_BASELINE_COMMIT"], dataset_sha256=hashlib.sha256(raw).hexdigest(), holdout_executed=False)
        with Path(os.environ["RWV_BASELINE_REPORT"]).open("x") as output:
            json.dump(result, output, ensure_ascii=False)
        print(json.dumps({key: result[key] for key in ['status', 'usage', 'seconds', 'required_group_recall', 'required_transmitted_excerpt_coverage']}, ensure_ascii=False), flush=True)
        self.assertEqual(result["status"], "completed", result["usage"])
        self.assertEqual(result["required_group_recall"], 1)
        self.assertFalse(result["private_sentinel_exposed"])
        searched = [row for trace in result["retrieval"] for row in trace["sources"]]
        self.assertTrue(any(row.get('read_mode') and not any(
            candidate['type'] == row['type'] and candidate['id'] == row['id'] and row['excerpt'] in candidate['excerpt']
            for candidate in searched) for row in result['transmitted_sources']), '必须把初始检索之外的实际补读内容发给模型')
        self.assertLessEqual(result["usage"]["evidence_chars"], 18000)
        self.assertLessEqual(result["usage"]["tool_calls"], 6)
        self.assertLessEqual(result["usage"]["model_calls"], 5)
