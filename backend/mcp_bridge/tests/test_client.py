import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from researchweave_mcp.client import ClientConfig, ConfigurationError, ResearchWeaveApiError, ResearchWeaveClient


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload = json.dumps(payload).encode()
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.payload


class ClientTests(unittest.TestCase):
    def test_configuration_requires_https_and_pat(self):
        with self.assertRaises(ConfigurationError):
            ClientConfig.from_env({"RWV_BASE_URL": "http://a510.example", "RWV_TOKEN": "rwv_pat_x"})
        with self.assertRaises(ConfigurationError):
            ClientConfig.from_env({"RWV_BASE_URL": "https://a510.example", "RWV_TOKEN": "other-token"})
        config = ClientConfig.from_env({
            "RWV_BASE_URL": "https://a510.example/base/",
            "RWV_TOKEN": "rwv_pat_example.secret",
        })
        self.assertEqual(config.base_url, "https://a510.example/base")

    def test_request_uses_rest_bearer_without_logging_or_returning_token(self):
        opener = Mock()
        opener.open.return_value = Response({"capabilities": ["materials.list"]}, headers={"X-Request-ID": "server-id"})
        config = ClientConfig(base_url="https://a510.example", token="rwv_pat_example.secret")
        result = ResearchWeaveClient(config, opener=opener).get_me()
        self.assertEqual(result["capabilities"], ["materials.list"])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://a510.example/api/v1/me")
        self.assertEqual(request.headers["Authorization"], "Bearer rwv_pat_example.secret")
        self.assertNotIn("rwv_pat_example.secret", str(result))

    def test_api_error_is_structured_and_does_not_include_token(self):
        opener = Mock()
        opener.open.side_effect = HTTPError(
            "https://a510.example/api/v1/materials",
            403,
            "Forbidden",
            {"X-Request-ID": "request-7"},
            io.BytesIO(json.dumps({"code": "scope_denied", "detail": "missing scope"}).encode()),
        )
        client = ResearchWeaveClient(
            ClientConfig(base_url="https://a510.example", token="rwv_pat_example.secret"),
            opener=opener,
        )
        with self.assertRaises(ResearchWeaveApiError) as caught:
            client.search_materials()
        self.assertEqual((caught.exception.status, caught.exception.code), (403, "scope_denied"))
        self.assertNotIn("rwv_pat_example.secret", str(caught.exception))
