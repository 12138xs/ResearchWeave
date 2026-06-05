from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings


DEFAULT_RELEASE = {
    "product": "A510知识库",
    "version": "v0.0.0",
    "released_at": "",
    "summary": "Release metadata is not available.",
    "migration_state": "unknown",
    "deployed_at": "",
    "git_commit": "",
    "source_repo": "",
    "source_ref": "",
    "artifact_hash": "",
    "dirty": "",
}


def sanitize_source_repo(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""

    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        host = parsed.hostname or ""
        if not host:
            return ""
        netloc = host
        if parsed.port:
            netloc = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))

    if "@" in value:
        _, host_and_path = value.split("@", 1)
        return host_and_path.split("?", 1)[0].split("#", 1)[0].rstrip("/")

    return value.split("?", 1)[0].split("#", 1)[0].rstrip("/")


@lru_cache(maxsize=1)
def load_release_info() -> dict[str, str]:
    release = DEFAULT_RELEASE.copy()
    release_path = next(
        (
            path
            for path in [
                Path(settings.BASE_DIR).parent / "release.json",
                Path(settings.BASE_DIR) / "release.json",
            ]
            if path.exists()
        ),
        None,
    )
    if release_path is not None:
        with release_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for key in release:
            value = payload.get(key)
            if value is not None:
                release[key] = str(value)
    current_release_path = next(
        (
            path
            for path in [
                Path(settings.BASE_DIR).parent / "current-release.json",
                Path(settings.BASE_DIR) / "current-release.json",
            ]
            if path.exists()
        ),
        None,
    )
    if current_release_path is not None:
        with current_release_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for key in release:
            value = payload.get(key)
            if value is not None:
                release[key] = str(value)
    configured_version = getattr(settings, "APP_VERSION", "")
    if configured_version:
        release["version"] = str(configured_version)
    release["source_repo"] = sanitize_source_repo(release.get("source_repo", ""))
    return release
