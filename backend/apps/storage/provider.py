from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


@dataclass(frozen=True)
class LocalStorageProvider:
    root: Path

    def resolve(self, logical_key: str) -> Path:
        clean = logical_key.strip().lstrip("/").replace("\\", "/")
        if ".." in Path(clean).parts:
            raise ValueError("invalid storage key")
        root = self.root.resolve()
        target = (root / clean).resolve()
        if not target.is_relative_to(root):
            raise ValueError("storage key escapes root")
        return target

    def ensure_runtime_dirs(self) -> list[Path]:
        dirs = [
            "quarantine/uploads",
            "objects/pdf",
            "objects/images",
            "objects/figures",
            "objects/attachments",
            "snapshots/markdown/papers",
            "snapshots/markdown/documents",
            "snapshots/obsidian",
            "snapshots/git-mirror",
            "exports/dify",
            "exports/wikijs",
            "tmp",
        ]
        created = []
        for item in dirs:
            path = self.resolve(item)
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
        return created


def get_storage_provider() -> LocalStorageProvider:
    return LocalStorageProvider(root=Path(settings.STORAGE_ROOT))
