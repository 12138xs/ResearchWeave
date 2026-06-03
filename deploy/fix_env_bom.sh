#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/data2/research_os}"
ENV_FILE="$ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE"
  exit 1
fi

backup="$ROOT/.env.bomfix-backup-$(date +%Y%m%d_%H%M%S)"
cp -p "$ENV_FILE" "$backup"

python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = path.read_bytes()
if data.startswith(b"\xef\xbb\xbf"):
    path.write_bytes(data[3:])
    print("bom_removed=true")
else:
    print("bom_removed=false")
print("bom_present=" + str(path.read_bytes().startswith(b"\xef\xbb\xbf")))
PY

echo "backup=$backup"
