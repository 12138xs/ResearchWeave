from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


class MiniMaxConfigError(RuntimeError):
    pass


class MiniMaxAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class MiniMaxResponse:
    content: str
    model: str
    usage: dict[str, Any]
    raw: dict[str, Any]


def call_minimax_chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
) -> MiniMaxResponse:
    api_key = getattr(settings, "MODEL_GATEWAY_API_KEY", "")
    if not api_key:
        raise MiniMaxConfigError("MiniMax API key is not configured.")

    base_url = getattr(settings, "MODEL_GATEWAY_BASE_URL", "https://api.minimax.io/v1").rstrip("/")
    model_name = model or getattr(settings, "DEFAULT_LLM_MODEL", "MiniMax-M2.7") or "MiniMax-M2.7"
    request_timeout = int(timeout or getattr(settings, "MODEL_GATEWAY_TIMEOUT_SECONDS", 60))
    token_limit = max_tokens or int(getattr(settings, "MODEL_GATEWAY_MAX_TOKENS", 1600))
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": token_limit,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        if tool_choice not in {"auto", "none"}:
            raise ValueError("Unsupported tool choice.")
        payload["tool_choice"] = tool_choice
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=request_timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _read_error_detail(exc)
        raise MiniMaxAPIError(f"MiniMax API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        if _is_timeout_error(exc.reason):
            raise MiniMaxAPIError(
                f"MiniMax API request timed out after {request_timeout} seconds. "
                "Increase PAPER_DEEP_LLM_TIMEOUT_SECONDS for deep reading jobs or retry with a shorter excerpt."
            ) from exc
        raise MiniMaxAPIError(f"MiniMax API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise MiniMaxAPIError(
            f"MiniMax API request timed out after {request_timeout} seconds. "
            "Increase PAPER_DEEP_LLM_TIMEOUT_SECONDS for deep reading jobs or retry with a shorter excerpt."
        ) from exc
    except json.JSONDecodeError as exc:
        raise MiniMaxAPIError("MiniMax API returned invalid JSON.") from exc

    choices = response_payload.get("choices") or []
    if not choices:
        raise MiniMaxAPIError("MiniMax API returned no choices.")
    message = choices[0].get("message") or {}
    content = _strip_thinking(str(message.get("content") or "")).strip()
    if not content and not (tools and message.get("tool_calls")):
        raise MiniMaxAPIError("MiniMax API returned an empty answer.")

    return MiniMaxResponse(
        content=content,
        model=str(response_payload.get("model") or model_name),
        usage=response_payload.get("usage") or {},
        raw=response_payload,
    )


def _strip_thinking(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()


def _read_error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return exc.reason or "request failed"
    if not body:
        return exc.reason or "request failed"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]
    detail = payload.get("error") or payload.get("base_resp") or payload
    return json.dumps(detail, ensure_ascii=False)[:500]


def _is_timeout_error(reason: object) -> bool:
    return isinstance(reason, TimeoutError) or "timed out" in str(reason).lower()
