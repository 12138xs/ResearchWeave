from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings


DEFAULT_RELEASE = {
    "product": "A510知识库",
    "version": "v0.0.0",
    "released_at": "",
    "summary": "Release metadata is not available.",
    "migration_state": "unknown",
}


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
    configured_version = getattr(settings, "APP_VERSION", "")
    if configured_version:
        release["version"] = str(configured_version)
    return release
