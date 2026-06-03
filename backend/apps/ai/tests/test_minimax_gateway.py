from __future__ import annotations

import json
from urllib.error import URLError
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.ai.minimax import MiniMaxAPIError, MiniMaxConfigError, call_minimax_chat


class MiniMaxGatewayTests(SimpleTestCase):
    @override_settings(MODEL_GATEWAY_API_KEY="", MODEL_GATEWAY_BASE_URL="https://api.minimaxi.com/v1")
    def test_requires_api_key(self) -> None:
        with self.assertRaises(MiniMaxConfigError):
            call_minimax_chat([{"role": "user", "content": "hello"}])

    @override_settings(
        MODEL_GATEWAY_API_KEY="test-key",
        MODEL_GATEWAY_BASE_URL="https://api.minimaxi.com/v1",
        DEFAULT_LLM_MODEL="MiniMax-M2.7",
        MODEL_GATEWAY_TIMEOUT_SECONDS=15,
    )
    @patch("apps.ai.minimax.urlopen")
    def test_calls_openai_compatible_chat_completions(self, mock_urlopen) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [{"message": {"content": "<think>scratch</think>\n\n中文回答"}}],
                        "usage": {"total_tokens": 42},
                    }
                ).encode("utf-8")

        mock_urlopen.return_value = FakeResponse()

        result = call_minimax_chat([{"role": "user", "content": "请总结论文"}])

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.minimaxi.com/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        self.assertEqual(payload["model"], "MiniMax-M2.7")
        self.assertEqual(payload["messages"][0]["content"], "请总结论文")
        self.assertEqual(result.content, "中文回答")
        self.assertEqual(result.usage["total_tokens"], 42)

    @override_settings(
        MODEL_GATEWAY_API_KEY="test-key",
        MODEL_GATEWAY_BASE_URL="https://api.minimaxi.com/v1",
        MODEL_GATEWAY_TIMEOUT_SECONDS=15,
    )
    @patch("apps.ai.minimax.urlopen")
    def test_call_accepts_per_request_timeout_override(self, mock_urlopen) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

        mock_urlopen.return_value = FakeResponse()

        call_minimax_chat([{"role": "user", "content": "hello"}], timeout=180)

        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 180)

    @override_settings(
        MODEL_GATEWAY_API_KEY="test-key",
        MODEL_GATEWAY_BASE_URL="https://api.minimaxi.com/v1",
        MODEL_GATEWAY_TIMEOUT_SECONDS=60,
    )
    @patch("apps.ai.minimax.urlopen")
    def test_timeout_error_message_names_timeout_seconds(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = URLError(TimeoutError("The read operation timed out"))

        with self.assertRaisesRegex(MiniMaxAPIError, "timed out after 60 seconds"):
            call_minimax_chat([{"role": "user", "content": "hello"}])
