#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-${RESEARCHWEAVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"
cd "$ROOT"

if [ ! -f release.json ]; then
  echo "ERROR: release.json not found"
  exit 1
fi

python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path(".")
release = json.loads((root / "release.json").read_text(encoding="utf-8"))
marker = {
    **release,
    "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}
(root / "current-release.json").write_text(
    json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"release={marker['version']}")
PY
