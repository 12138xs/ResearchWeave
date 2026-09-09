import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.ai.minimax import MiniMaxAPIError, call_minimax_chat
from apps.assistant.agent import TOOLS


@override_settings(MODEL_GATEWAY_API_KEY="test-placeholder")
class GatewayToolTests(SimpleTestCase):
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
