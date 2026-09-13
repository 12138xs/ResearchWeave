from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from researchweave_mcp import __version__


MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ConfigurationError(ValueError):
    pass


class ResearchWeaveApiError(RuntimeError):
    def __init__(self, *, status: int | None, code: str, detail: str, request_id: str = ""):
        self.status = status
        self.code = code
        self.detail = detail
        self.request_id = request_id
        suffix = f" request_id={request_id}" if request_id else ""
        super().__init__(f"A510 API error ({code}, status={status}): {detail}{suffix}")


@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    token: str
    timeout_seconds: float = 30.0
    ca_bundle: str | None = None

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        base_url = str(env.get("RWV_BASE_URL", "")).strip().rstrip("/")
        token = str(env.get("RWV_TOKEN", "")).strip()
        if not base_url:
            raise ConfigurationError("RWV_BASE_URL is required.")
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError("RWV_BASE_URL must be an HTTPS origin or base path without credentials or query data.")
        if not token:
            raise ConfigurationError("RWV_TOKEN is required.")
        if not token.startswith("rwv_pat_"):
            raise ConfigurationError("RWV_TOKEN is not a ResearchWeave personal access token.")
        try:
            timeout = float(env.get("RWV_TIMEOUT_SECONDS", "30"))
        except (TypeError, ValueError) as error:
            raise ConfigurationError("RWV_TIMEOUT_SECONDS must be a number.") from error
        if timeout <= 0 or timeout > 120:
            raise ConfigurationError("RWV_TIMEOUT_SECONDS must be between 0 and 120.")
        ca_bundle = str(env.get("RWV_CA_BUNDLE", "")).strip() or None
        return cls(base_url=base_url, token=token, timeout_seconds=timeout, ca_bundle=ca_bundle)


class ResearchWeaveClient:
    def __init__(self, config: ClientConfig):
        self.config = config
        self._ssl_context = ssl.create_default_context(cafile=config.ca_bundle)

    @classmethod
    def from_env(cls, env=None):
        return cls(ClientConfig.from_env(env))

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_id = str(uuid4())
        request = Request(
            self.config.base_url + "/api/v1/" + path.lstrip("/"),
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "User-Agent": f"researchweave-mcp/{__version__}",
                "X-Request-ID": request_id,
                "X-ResearchWeave-Client": f"researchweave-mcp/{__version__}",
            },
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds, context=self._ssl_context) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ResearchWeaveApiError(
                        status=response.status,
                        code="response_too_large",
                        detail="A510 response exceeded the bridge limit.",
                        request_id=response.headers.get("X-Request-ID", request_id),
                    )
                return json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as error:
            raw = error.read(MAX_RESPONSE_BYTES)
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = {}
            raise ResearchWeaveApiError(
                status=error.code,
                code=str(data.get("code") or "http_error"),
                detail=str(data.get("detail") or "A510 rejected the request."),
                request_id=error.headers.get("X-Request-ID", request_id),
            ) from None
        except (URLError, TimeoutError, ssl.SSLError) as error:
            raise ResearchWeaveApiError(
                status=None,
                code="connection_failed",
                detail=str(getattr(error, "reason", error)),
                request_id=request_id,
            ) from None

    def get_me(self):
        return self.request("GET", "me")

    def search_materials(self, query: str = ""):
        suffix = "?" + urlencode({"q": query}) if query else ""
        return self.request("GET", "materials" + suffix)

    def get_material(self, material_id: int):
        return self.request("GET", f"materials/{material_id}")

    def search_evidence(self, query: str, *, limit: int = 10, material_id: int | None = None):
        payload: dict[str, Any] = {"q": query, "limit": limit}
        if material_id is not None:
            payload["material_id"] = material_id
        return self.request("POST", "evidence/search", payload)

    def build_context_bundle(self, question: str, *, material_ids: list[int] | None = None, limit: int = 10):
        return self.request("POST", "context-bundles", {
            "question": question,
            "material_ids": material_ids or [],
            "limit": limit,
        })

    def get_context_bundle(self, bundle_id: str):
        return self.request("GET", f"context-bundles/{bundle_id}")

