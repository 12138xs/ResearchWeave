#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-${RESEARCHWEAVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"
cd "$ROOT"

if [ ! -f release.json ]; then
  echo "ERROR: release.json not found"
  exit 1
fi

python3 - <<'PY'
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

root = Path(".")
release = json.loads((root / "release.json").read_text(encoding="utf-8"))


def command_output(args):
    try:
        return subprocess.check_output(args, cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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
        return value.split("@", 1)[1].split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return value.split("?", 1)[0].split("#", 1)[0].rstrip("/")


git_commit = os.environ.get("RESEARCHWEAVE_GIT_COMMIT") or command_output(["git", "rev-parse", "HEAD"])
source_ref = os.environ.get("RESEARCHWEAVE_SOURCE_REF") or command_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
source_repo = sanitize_source_repo(
    os.environ.get("RESEARCHWEAVE_SOURCE_REPO") or command_output(["git", "config", "--get", "remote.origin.url"])
)
dirty = os.environ.get("RESEARCHWEAVE_DIRTY")
if dirty is None:
    dirty = "true" if command_output(["git", "status", "--short"]) else "false"

marker = {
    **release,
    "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "git_commit": git_commit,
    "source_repo": source_repo,
    "source_ref": source_ref,
    "artifact_hash": os.environ.get("RESEARCHWEAVE_ARTIFACT_HASH") or file_sha256(root / "frontend" / "dist" / "index.html"),
    "dirty": dirty,
}
(root / "current-release.json").write_text(
    json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"release={marker['version']}")
PY
