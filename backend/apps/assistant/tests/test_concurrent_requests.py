from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TransactionTestCase

from apps.assistant.models import AssistantExchange, AssistantSession
from apps.assistant.services import Conflict, create_assistant_exchange
from apps.tasks.models import TaskRecord


class ConcurrentRequestTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="concurrent-owner")

    def requests(self, session_ids, request_ids):
        barrier = Barrier(len(session_ids))
        def submit(pair):
            session_id, request_id = pair
            try:
                session = AssistantSession.objects.get(pk=session_id)
                barrier.wait(timeout=10)
                try:
                    return create_assistant_exchange(session, "PINN", request_id).pk
                except Conflict:
                    return None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(session_ids)) as pool:
            return list(pool.map(submit, zip(session_ids, request_ids)))

    @patch("apps.assistant.services._publish")
    def test_simultaneous_duplicate_messages_dispatch_once(self, publish):
        session = AssistantSession.objects.create(title="duplicate", created_by=self.owner)
        request_id = uuid4()
        result = self.requests([session.pk] * 4, [request_id] * 4)
        self.assertEqual(len(set(result)), 1)
        self.assertIsNotNone(result[0])
        self.assertEqual(AssistantExchange.objects.count(), 1)
        self.assertEqual(TaskRecord.objects.filter(task_type="research_agent").count(), 1)
        publish.assert_called_once()

    @patch("apps.assistant.services._publish")
    def test_simultaneous_sessions_cannot_exceed_per_user_limit(self, publish):
        sessions = [AssistantSession.objects.create(title=str(index), created_by=self.owner) for index in range(5)]
        result = self.requests([row.pk for row in sessions], [uuid4() for _ in sessions])
        self.assertEqual(sum(value is not None for value in result), 2)
        self.assertEqual(AssistantExchange.objects.filter(status="queued").count(), 2)
        self.assertEqual(publish.call_count, 2)
