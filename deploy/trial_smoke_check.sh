#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${RESEARCH_OS_BASE_URL:-http://127.0.0.1:30888}"
USERNAME="${RESEARCH_OS_SMOKE_USERNAME:-}"
PASSWORD="${RESEARCH_OS_SMOKE_PASSWORD:-}"
DRY_RUN=0
PYTHON_BIN="python"

if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
fi

checks=(
  "GET /api/health/"
  "GET /api/me/"
  "POST /api/auth/login/"
  "GET /api/papers/"
  "GET /api/papers/{first_id}/"
  "GET /api/tasks/"
  "GET /"
  "GET /papers"
  "GET /papers/upload"
  "GET /papers/qa"
  "GET /tasks"
)

if [ "$DRY_RUN" = "1" ]; then
  printf '%s\n' "${checks[@]}"
  exit 0
fi

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: missing required command: $1" >&2
    exit 1
  fi
}

need curl
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "ERROR: missing required command: python or python3" >&2
    exit 1
  fi
fi

COOKIE_JAR="$(mktemp)"
BODY_FILE="$(mktemp)"
cleanup() {
  rm -f "$COOKIE_JAR" "$BODY_FILE"
}
trap cleanup EXIT

request() {
  local method="$1"
  local path="$2"
  local expected="${3:-200}"
  local data="${4:-}"
  local status
  if [ -n "$data" ]; then
    status="$(
      curl -sS -o "$BODY_FILE" -w "%{http_code}" \
        -X "$method" \
        -H "Content-Type: application/json" \
        -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
        --data "$data" \
        "$BASE_URL$path"
    )"
  else
    status="$(
      curl -sS -o "$BODY_FILE" -w "%{http_code}" \
        -X "$method" \
        -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
        "$BASE_URL$path"
    )"
  fi
  if [ "$status" != "$expected" ]; then
    echo "ERROR: $method $path returned $status, expected $expected" >&2
    cat "$BODY_FILE" >&2
    exit 1
  fi
  echo "OK: $method $path"
}

contains() {
  local expected="$1"
  if ! grep -F "$expected" "$BODY_FILE" >/dev/null 2>&1; then
    echo "ERROR: response did not contain: $expected" >&2
    cat "$BODY_FILE" >&2
    exit 1
  fi
}

first_paper_id() {
  "$PYTHON_BIN" - "$BODY_FILE" <<'PY'
from __future__ import annotations

import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
items = payload.get("results", payload) if isinstance(payload, dict) else payload
if not items:
    raise SystemExit("")
print(items[0]["id"])
PY
}

echo "== Trial Smoke Check =="
echo "base_url=$BASE_URL"

request GET "/api/health/"
request GET "/api/me/"
contains '"authenticated":false'

if [ -n "$USERNAME" ] && [ -n "$PASSWORD" ]; then
  login_payload="$("$PYTHON_BIN" - "$USERNAME" "$PASSWORD" <<'PY'
from __future__ import annotations

import json
import sys

print(json.dumps({"username": sys.argv[1], "password": sys.argv[2]}))
PY
)"
  request POST "/api/auth/login/" 200 "$login_payload"
  contains '"authenticated":true'
  request GET "/api/me/"
  contains "\"username\":\"$USERNAME\""
else
  echo "SKIP: POST /api/auth/login/ (set RESEARCH_OS_SMOKE_USERNAME and RESEARCH_OS_SMOKE_PASSWORD)"
fi

request GET "/api/papers/"
paper_id="$(first_paper_id || true)"
if [ -n "$paper_id" ]; then
  request GET "/api/papers/$paper_id/"
else
  echo "SKIP: GET /api/papers/{first_id}/ (no papers found)"
fi
request GET "/api/tasks/"

request GET "/"
request GET "/papers"
request GET "/papers/upload"
request GET "/papers/qa"
request GET "/tasks"

echo "trial smoke ok"
