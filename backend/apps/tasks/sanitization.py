from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


STORAGE_KEY_RE = re.compile(r"\bquarantine/uploads/[^\s'\"),;]+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?<!\w)[A-Za-z]:\\[^\s'\"),;]+")
POSIX_PATH_RE = re.compile(r"(?<!\w)/(?:home|var|tmp|mnt|data|opt|srv|Users)/[^\s'\"),;]+")
SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*([^\s'\"),;]+)"
)


def sanitize_task_error(value: object) -> str:
    text = " ".join(str(value or "").split())
    text = STORAGE_KEY_RE.sub("[storage key redacted]", text)
    text = WINDOWS_PATH_RE.sub("[path redacted]", text)
    text = POSIX_PATH_RE.sub("[path redacted]", text)
    text = SECRET_RE.sub(r"\1=[secret redacted]", text)
    return text


def sanitize_task_result(value: object) -> object:
    if isinstance(value, str):
        return sanitize_task_error(value)
    if isinstance(value, Mapping):
        return {key: sanitize_task_result(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [sanitize_task_result(item) for item in value]
    return value
