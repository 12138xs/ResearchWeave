import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from apps.assistant.models import AssistantSession, AssistantExchange
from apps.tasks.models import TaskRecord


class StartConversationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='start-owner')
        self.other = get_user_model().objects.create_user(username='start-other')
        self.client.force_login(self.user)
        self.payload = {'question': '复杂几何上的算子有什么限制？', 'request_id': str(uuid.uuid4())}

    @patch('apps.assistant.tasks.answer_question.apply_async')
    def test_first_question_and_lost_response_retry_create_one_task(self, publish):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post('/api/assistant/start/', self.payload, content_type='application/json')
            retry = self.client.post('/api/assistant/start/', self.payload, content_type='application/json')
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()['id'], retry.json()['id'])
        self.assertEqual(first.json()['scope_json'], {})
        self.assertEqual(AssistantSession.objects.count(), 1)
        self.assertEqual(AssistantExchange.objects.count(), 1)
        self.assertEqual(TaskRecord.objects.filter(task_type='research_agent').count(), 1)
        self.assertEqual(publish.call_count, 1)

    def test_conflicting_request_and_invalid_scope_leave_no_orphan_session(self):
        self.client.post('/api/assistant/start/', self.payload, content_type='application/json')
        response = self.client.post('/api/assistant/start/', {**self.payload, 'question': '另一个问题'}, content_type='application/json')
        self.assertEqual(response.status_code, 409)
        invalid = {**self.payload, 'request_id': str(uuid.uuid4()), 'scope_json': {'material_ids': [999]}}
        self.assertEqual(self.client.post('/api/assistant/start/', invalid, content_type='application/json').status_code, 400)
        self.assertEqual(AssistantSession.objects.count(), 1)

    def test_reused_request_id_is_private_to_user(self):
        first = self.client.post('/api/assistant/start/', self.payload, content_type='application/json')
        self.client.force_login(self.other)
        second = self.client.post('/api/assistant/start/', self.payload, content_type='application/json')
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertNotEqual(first.json()['id'], second.json()['id'])

    def test_concurrency_limit_rolls_back_empty_session(self):
        for _ in range(2):
            response = self.client.post('/api/assistant/start/', {**self.payload, 'request_id': str(uuid.uuid4())}, content_type='application/json')
            self.assertEqual(response.status_code, 202)
        response = self.client.post('/api/assistant/start/', {**self.payload, 'request_id': str(uuid.uuid4())}, content_type='application/json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(AssistantSession.objects.count(), 2)
