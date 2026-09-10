import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.ai.minimax import MiniMaxAPIError, call_minimax_chat
from apps.assistant.agent import TOOLS


@override_settings(MODEL_GATEWAY_API_KEY="test-placeholder")
class GatewayToolTests(SimpleTestCase):
    @patch("apps.ai.minimax.urlopen")
    def test_empty_answer_preserves_usage_without_exposing_reasoning(self, open_url):
        result = MagicMock()
        result.__enter__.return_value.read.return_value = json.dumps({"choices": [{"finish_reason": "length", "message": {
            "content": "<think>private reasoning</think>"}}], "usage": {"total_tokens": 2400}}).encode()
        open_url.return_value = result
        with self.assertRaises(MiniMaxAPIError) as caught:
            call_minimax_chat([])
        self.assertEqual(caught.exception.usage["total_tokens"], 2400)
        self.assertEqual(caught.exception.code, "output_limit")
        self.assertNotIn("private reasoning", str(caught.exception))

    @patch("apps.ai.minimax.urlopen")
    def test_explicit_tool_choice_is_sent_only_when_requested(self, open_url):
        result = MagicMock()
        result.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": "answer"}}]}).encode()
        open_url.return_value = result
        call_minimax_chat([], tools=TOOLS, tool_choice="none")
        self.assertEqual(json.loads(open_url.call_args.args[0].data)["tool_choice"], "none")
        call_minimax_chat([])
        self.assertNotIn("tool_choice", json.loads(open_url.call_args.args[0].data))

    @patch("apps.ai.minimax.urlopen")
    def test_empty_content_is_only_allowed_for_tool_response(self, open_url):
        result = MagicMock()
        result.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {
            "role": "assistant", "content": None, "tool_calls": [{"id": "call-1"}],
        }}]}).encode()
        open_url.return_value = result
        response = call_minimax_chat([{"role": "user", "content": "test"}], tools=TOOLS, model="MiniMax-M3")
        self.assertEqual(response.content, "")
        self.assertEqual(json.loads(open_url.call_args.args[0].data)["tools"], TOOLS)
        with self.assertRaises(MiniMaxAPIError):
            call_minimax_chat([{"role": "user", "content": "test"}])
