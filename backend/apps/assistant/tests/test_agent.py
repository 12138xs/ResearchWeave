import json
import os
import uuid
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.assistant.agent import run_exchange
from apps.assistant.models import AssistantExchange, AssistantSession
from apps.assistant.services import control_exchange
from apps.documents.models import Document, DocumentVersion


def reply(answer=None, calls=None):
    message = {"role": "assistant", "content": json.dumps(answer) if answer else "", "reasoning_details": [{"text": "private reasoning"}]}
    if calls:
        message["tool_calls"] = calls
    return SimpleNamespace(content=message["content"], usage={"total_tokens": 10}, raw={"choices": [{"message": message}]})


def search(query="PINN"):
    return reply(calls=[{"id": "call-1", "type": "function", "function": {"name": "search_knowledge", "arguments": json.dumps({"query": query})}}])


class AgentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="agent-owner")
        self.other = get_user_model().objects.create_user(username="agent-other")
        self.client.force_login(self.user)
        self.session = AssistantSession.objects.create(title="研究", created_by=self.user)
        document = Document.objects.create(title="PINN")
        self.version = DocumentVersion.objects.create(document=document, markdown="PINN residual and boundary losses")
        self.exchange = AssistantExchange.objects.create(session=self.session, question="PINN 有何依据", status="queued", request_id=uuid.uuid4())
        self.url = f"/api/assistant/sessions/{self.session.pk}/exchanges/{self.exchange.pk}/"

    @patch("apps.assistant.agent.call_minimax_chat")
    def test_tool_loop_citations_and_reasoning_continuity(self, model):
        model.side_effect = [search(), reply({"answer": "材料包含残差损失 [S1]。建议另行验证边界误差。", "source_ids": ["S1"]})]
        run_exchange(self.exchange.pk, 1)
        self.exchange.refresh_from_db()
        self.assertEqual(self.exchange.status, "completed")
        self.assertEqual(self.exchange.sources[0]["id"], self.version.pk)
        self.assertEqual(self.exchange.usage["total_tokens"], 20)
        self.assertIn("reasoning_details", model.call_args.args[0][-2])
        self.assertNotIn("private reasoning", json.dumps(self.client.get(self.url).json()))
        run_exchange(self.exchange.pk, 1)
        self.assertEqual(model.call_count, 2)

    @patch("apps.assistant.agent.call_minimax_chat")
    def test_forged_source_is_not_published(self, model):
        model.side_effect = [search(), reply({"answer": "结论 [S999]", "source_ids": ["S999"]})]
        run_exchange(self.exchange.pk, 1)
        self.exchange.refresh_from_db()
        self.assertEqual(self.exchange.status, "failed")
        self.assertEqual(self.exchange.answer, "")

    @patch("apps.assistant.agent.call_minimax_chat")
    def test_no_match_has_deterministic_insufficient_answer(self, model):
        model.side_effect = [search("zzzz_nomatch"), reply({"answer": "invented"})]
        run_exchange(self.exchange.pk, 1)
        self.exchange.refresh_from_db()
        self.assertEqual(self.exchange.status, "completed")
        self.assertIn("未检索到足够材料", self.exchange.answer)
        self.assertEqual(self.exchange.sources, [])

    @patch("apps.assistant.agent.call_minimax_chat")
    def test_cancellation_discards_late_model_reply(self, model):
        def cancel(*args, **kwargs):
            control_exchange(self.exchange, "cancel", 1)
            return search()
        model.side_effect = cancel
        run_exchange(self.exchange.pk, 1)
        self.exchange.refresh_from_db()
        self.assertEqual(self.exchange.status, "cancelled")
        self.assertEqual(self.exchange.answer, "")
        model.assert_called_once()

    @patch("apps.assistant.agent.call_minimax_chat", side_effect=RuntimeError("secret API credential"))
    def test_gateway_failure_is_sanitized(self, model):
        run_exchange(self.exchange.pk, 1)
        response = self.client.get(self.url)
        self.assertEqual(response.json()["status"], "failed")
        self.assertNotIn("secret", response.content.decode())

    @patch("apps.assistant.services._publish")
    def test_duplicate_request_and_conflicting_question(self, publish):
        self.exchange.delete()
        url = f"/api/assistant/sessions/{self.session.pk}/messages/"
        payload = {"question": "PINN", "request_id": str(uuid.uuid4())}
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(url, payload, content_type="application/json")
            second = self.client.post(url, payload, content_type="application/json")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["id"], second.json()["id"])
        publish.assert_called_once()
        payload["question"] = "different"
        self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 409)
        payload["request_id"] = str(uuid.uuid4())
        self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 409)

    @patch("apps.assistant.services._publish")
    def test_retry_is_idempotent_and_old_attempt_cannot_run(self, publish):
        control_exchange(self.exchange, "cancel", 1)
        with self.captureOnCommitCallbacks(execute=True):
            retried = control_exchange(self.exchange, "retry", 1)
            repeated = control_exchange(self.exchange, "retry", 1)
        self.assertEqual(retried.attempt, 2)
        self.assertEqual(repeated.attempt, 2)
        publish.assert_called_once()
        run_exchange(self.exchange.pk, 1)
        self.exchange.refresh_from_db()
        self.assertEqual(self.exchange.status, "queued")

    def test_other_user_cannot_read_control_or_stream(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"action": "cancel", "attempt": 1}, content_type="application/json").status_code, 404)
        self.assertEqual(self.client.get(self.url + "progress/").status_code, 404)

    @patch("apps.assistant.services._publish")
    def test_stream_reconnect_does_not_enqueue(self, publish):
        for _ in range(2):
            response = self.client.get(self.url + "progress/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"event: progress", b"".join(response.streaming_content))
        publish.assert_not_called()

    def test_deleted_source_hides_historical_answer(self):
        self.exchange.status, self.exchange.answer = "completed", "sensitive derived answer"
        self.exchange.sources = [{"type": "document", "id": self.version.pk}]
        self.exchange.save()
        self.version.delete()
        payload = self.client.get(f"/api/assistant/sessions/{self.session.pk}/").json()
        self.assertNotIn("sensitive", json.dumps(payload))

    def test_per_user_pending_work_is_bounded_across_sessions(self):
        second = AssistantSession.objects.create(title="second", created_by=self.user)
        AssistantExchange.objects.create(session=second, question="second", status="running")
        third = AssistantSession.objects.create(title="third", created_by=self.user)
        result = self.client.post(f"/api/assistant/sessions/{third.pk}/messages/",
            {"question": "PINN", "request_id": str(uuid.uuid4())}, content_type="application/json")
        self.assertEqual(result.status_code, 409)
        self.assertEqual(third.exchanges.count(), 0)

    @patch("apps.assistant.agent.call_minimax_chat")
    def test_multi_turn_history_is_bounded_and_retrieves_again(self, model):
        previous = self.exchange
        previous.status, previous.answer, previous.model = "completed", "先前答案 [S1]", "MiniMax-M3"
        previous.sources = [{"type": "document", "id": self.version.pk}]
        previous.save()
        followup = AssistantExchange.objects.create(session=self.session, question="如何改进", status="queued")
        model.side_effect = [search(), reply({"answer": "建议验证损失权重 [S1]", "source_ids": ["S1"]})]
        run_exchange(followup.pk, 1)
        followup.refresh_from_db()
        self.assertEqual(followup.status, "completed")
        self.assertIn("先前答案", str(model.call_args.args[0]))
        self.assertEqual(followup.usage["tool_calls"], 1)

    @patch("apps.assistant.agent.call_minimax_chat")
    def test_source_removed_during_generation_discards_answer(self, model):
        def respond(*args, **kwargs):
            if model.call_count == 1:
                return search()
            self.version.delete()
            return reply({"answer": "旧内容 [S1]", "source_ids": ["S1"]})
        model.side_effect = respond
        run_exchange(self.exchange.pk, 1)
        self.exchange.refresh_from_db()
        self.assertEqual(self.exchange.status, "failed")
        self.assertEqual(self.exchange.answer, "")

    @patch("apps.assistant.agent.call_minimax_chat")
    def test_unapproved_tool_cannot_execute(self, model):
        model.return_value = reply(calls=[{"id": "bad", "function": {"name": "delete_document", "arguments": "{}"}}])
        run_exchange(self.exchange.pk, 1)
        self.exchange.refresh_from_db()
        self.assertEqual(self.exchange.status, "failed")
        self.assertTrue(DocumentVersion.objects.filter(pk=self.version.pk).exists())

    @patch("apps.assistant.agent.call_minimax_chat")
    def test_tool_loop_is_bounded(self, model):
        model.return_value = search()
        run_exchange(self.exchange.pk, 1)
        self.exchange.refresh_from_db()
        self.assertEqual(self.exchange.status, "failed")
        self.assertEqual(model.call_count, 4)

    @patch("apps.assistant.tasks.answer_question.apply_async", side_effect=RuntimeError("secret broker"))
    def test_dispatch_failure_is_visible_and_sanitized(self, dispatch):
        self.exchange.delete()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/api/assistant/sessions/{self.session.pk}/messages/",
                {"question": "PINN", "request_id": str(uuid.uuid4())}, content_type="application/json")
        row = AssistantExchange.objects.get(pk=response.json()["id"])
        self.assertEqual(row.status, "failed")
        self.assertNotIn("secret", row.error)


@skipUnless(os.getenv("RWV_LIVE_MINIMAX") == "1", "需显式启用服务器真实模型验收")
class LiveAgentTests(TestCase):
    def test_real_tool_call_and_cited_answer(self):
        user = get_user_model().objects.create_user(username="agent-live")
        document = Document.objects.create(title="PINN synthetic example")
        DocumentVersion.objects.create(document=document, markdown="Physics informed neural networks (PINNs) penalize PDE residuals and boundary condition errors in their loss. This synthetic note provides no numerical benchmark or proof of convergence.")
        session = AssistantSession.objects.create(title="真实接口小样", created_by=user, scope_json={"document_ids": [document.pk]})
        exchange = AssistantExchange.objects.create(session=session, question="根据材料说明 PINN 使用什么损失，并给出一条需验证的改进建议。", status="queued")
        from apps.ai.minimax import call_minimax_chat
        def observe(*args, **kwargs):
            response = call_minimax_chat(*args, **kwargs)
            choice = response.raw["choices"][0]
            print("Live response:", choice.get("finish_reason"), "content_chars=", len(response.content),
                  "tools=", len(choice["message"].get("tool_calls") or []), "tokens=", response.usage.get("total_tokens"))
            return response
        with patch("apps.assistant.agent.call_minimax_chat", side_effect=observe):
            run_exchange(exchange.pk, 1)
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, "completed", f"{exchange.error} {exchange.usage}")
        self.assertTrue(exchange.sources)
        self.assertIn("[S", exchange.answer)
        self.assertGreaterEqual(exchange.usage["tool_calls"], 1)
        print(f"Live agent: calls={exchange.usage['model_calls']}, tools={exchange.usage['tool_calls']}, tokens={exchange.usage['total_tokens']}")
