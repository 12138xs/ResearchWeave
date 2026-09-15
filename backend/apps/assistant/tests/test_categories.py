import json
import uuid
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.assistant.agent import run_exchange
from apps.assistant.knowledge import search_knowledge, source_allowed
from apps.assistant.models import AssistantSession, AssistantExchange, PersonalEntry
from apps.assistant.reading import read_source, find_in_source
from apps.assistant.serializers import validate_scope, AssistantExchangeSerializer
from apps.assistant.tests.test_agent import reply, search
from apps.documents.models import Document, DocumentVersion
from apps.materials.models import Material, MaterialVersion, Evidence, LegacyPaperLink
from apps.papers.models import Paper


class CategoryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='category-owner')
        self.other = get_user_model().objects.create_user(username='category-other')
        self.client.force_login(self.user)
        self.paper = self.material('paper', 'PINN paper evidence')
        self.document = self.material('document', 'PINN document forbidden_marker')
        self.proposal = self.material('proposal', 'PINN proposal forbidden_marker')
        doc = Document.objects.create(title='PINN legacy document')
        DocumentVersion.objects.create(document=doc, markdown='PINN legacy forbidden_marker')
        PersonalEntry.objects.create(owner=self.user, kind='memory', title='private', body='forbidden_marker')
        PersonalEntry.objects.create(owner=self.other, kind='note', title='PINN private', body='PINN private forbidden_marker')
        self.scope = {'content_types': ['paper']}

    def material(self, category, text):
        material = Material.objects.create(owner=self.user, title='PINN', content_type=category)
        version = MaterialVersion.objects.create(material=material, number=1, sha256=uuid.uuid4().hex * 2,
            filename='synthetic.md', format='md', size=100, status='ready', created_by=self.user)
        return Evidence.objects.create(version=version, ordinal=1, text=text, line_start=1, line_end=1)

    def test_category_filters_native_and_legacy_sources_before_ranking(self):
        rows = search_knowledge(self.user, self.scope, 'PINN')
        self.assertEqual([(r['type'], r['id']) for r in rows], [('material', self.paper.pk)])
        rows = search_knowledge(self.user, {'content_types': ['document']}, 'PINN')
        self.assertEqual({r['type'] for r in rows}, {'material', 'document'})
        self.assertNotIn(self.proposal.pk, [r['id'] for r in search_knowledge(self.user, {}, 'PINN') if r['type'] == 'material'])

    def test_invalid_empty_and_proposal_scopes_rejected(self):
        for value in [[], ['proposal'], ['invalid'], [True], 'paper']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_scope({'content_types': value}, self.user)
        self.assertEqual(search_knowledge(self.user, {'content_types': []}, 'PINN'), [])
        self.assertEqual(validate_scope({}, self.user), {})

    def test_category_and_id_intersection(self):
        scope = {**self.scope, 'material_ids': [self.document.version.material_id]}
        self.assertEqual(search_knowledge(self.user, scope, 'PINN'), [])
        scope = {**self.scope, 'material_ids': [self.paper.version.material_id]}
        self.assertEqual(len(search_knowledge(self.user, scope, 'PINN')), 1)

    def test_new_material_and_private_access(self):
        added = self.material('paper', 'PINN new paper')
        self.assertIn(added.pk, [r['id'] for r in search_knowledge(self.user, self.scope, 'PINN')])
        added.version.material.visibility = 'private'
        added.version.material.save()
        self.assertNotIn(added.pk, [r['id'] for r in search_knowledge(self.other, self.scope, 'PINN')])

    def test_reclassification_blocks_reads_history_and_final_checks(self):
        source = search_knowledge(self.user, self.scope, 'PINN')[0]
        session = AssistantSession.objects.create(created_by=self.user, scope_json=self.scope)
        exchange = AssistantExchange.objects.create(session=session, question='PINN', answer='saved', sources=[source])
        Material.objects.filter(pk=self.paper.version.material_id).update(content_type='document')
        self.assertFalse(source_allowed(source, self.user, self.scope))
        for read in [lambda: read_source(self.user, self.scope, source), lambda: find_in_source(self.user, self.scope, source, query='PINN')]:
            with self.assertRaises(ValueError):
                read()
        self.assertEqual(AssistantExchangeSerializer(exchange).data['sources'], [])

    def test_proposal_block_is_sticky_and_owner_only(self):
        material = self.paper.version.material
        url = f'/api/materials/{material.pk}/classification/'
        response = self.client.post(url, {'source_kind': 'human_record', 'content_type': 'proposal'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['internal_ai_blocked'])
        self.client.post(url, {'source_kind': 'human_record', 'content_type': 'paper'}, content_type='application/json')
        self.assertEqual(search_knowledge(self.user, self.scope, 'PINN'), [])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {'source_kind': 'human_record', 'content_type': 'paper'}, content_type='application/json').status_code, 404)

    def test_legacy_backfill_dry_run_and_idempotence(self):
        self.paper.version.material.content_type = 'other'
        self.paper.version.material.save()
        legacy = Paper.objects.create(title='PINN legacy')
        LegacyPaperLink.objects.create(paper=legacy, version=self.paper.version, original_sha256=self.paper.version.sha256)
        call_command('classify_linked_papers', stdout=StringIO())
        self.paper.version.material.refresh_from_db()
        self.assertEqual(self.paper.version.material.content_type, 'other')
        call_command('classify_linked_papers', apply=True, stdout=StringIO())
        output = StringIO()
        call_command('classify_linked_papers', apply=True, stdout=output)
        self.assertIn('applied: 0', output.getvalue())
        self.assertEqual(len(search_knowledge(self.user, self.scope, 'PINN')), 1)

    @patch('apps.assistant.agent.call_minimax_chat')
    def test_actual_model_payload_excludes_unselected_material_and_memory(self, model):
        model.side_effect = [search('PINN'), reply({'answer': '材料事实 [S1]'}), reply({'answer': '材料事实 [S1]'})]
        session = AssistantSession.objects.create(created_by=self.user, scope_json=self.scope)
        exchange = AssistantExchange.objects.create(session=session, question='PINN', status='queued', request_id=uuid.uuid4())
        run_exchange(exchange.pk, 1)
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, 'completed', exchange.usage)
        payload = json.dumps([call.args[0] for call in model.call_args_list], ensure_ascii=False)
        self.assertIn('PINN paper evidence', payload)
        self.assertNotIn('forbidden_marker', payload)
        self.assertEqual(model.call_count, 3)

    @patch('apps.assistant.tasks.answer_question.apply_async')
    def test_session_scope_persists_and_conflicting_retry_is_rejected(self, publish):
        payload = {'question': 'PINN', 'request_id': str(uuid.uuid4()), 'scope_json': self.scope}
        response = self.client.post('/api/assistant/start/', payload, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['scope_json'], self.scope)
        payload['scope_json'] = {'content_types': ['document']}
        conflict = self.client.post('/api/assistant/start/', payload, content_type='application/json')
        self.assertEqual(conflict.status_code, 409)

    @patch('apps.search.assisted._json_reply')
    def test_assisted_search_does_not_send_proposals(self, model):
        from apps.search.assisted import assisted_search
        model.side_effect = [{'queries': ['PINN']}, {'evidence_ids': []}]
        assisted_search(self.user, {'q': 'PINN'})
        self.assertEqual(model.call_count, 2)
        candidates = json.loads(model.call_args_list[1].args[0][1]['content'])['candidates']
        self.assertNotIn(self.proposal.pk, [r['evidence_id'] for r in candidates])

    @patch('apps.assistant.agent.call_minimax_chat')
    def test_reclassification_during_model_request_stops_next_transmission(self, model):
        def change(messages, **kwargs):
            if model.call_count == 1:
                return search('PINN')
            Material.objects.filter(pk=self.paper.version.material_id).update(content_type='proposal', internal_ai_blocked=True)
            return reply({'answer': '材料事实 [S1]'})
        model.side_effect = change
        session = AssistantSession.objects.create(created_by=self.user, scope_json=self.scope)
        exchange = AssistantExchange.objects.create(session=session, question='PINN', status='queued', request_id=uuid.uuid4())
        run_exchange(exchange.pk, 1)
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, 'failed')
        self.assertEqual(model.call_count, 2)
