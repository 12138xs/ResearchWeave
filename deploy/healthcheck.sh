#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-${RESEARCHWEAVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"
cd "$ROOT"
PUBLIC_BASE_URL_VALUE="${PUBLIC_BASE_URL:-}"
if [ -z "$PUBLIC_BASE_URL_VALUE" ] && [ -f .env ]; then
  PUBLIC_BASE_URL_VALUE="$(grep -m1 '^PUBLIC_BASE_URL=' .env | cut -d= -f2- || true)"
fi
HEALTH_HOST="${RESEARCH_OS_HEALTH_HOST:-$(printf '%s' "$PUBLIC_BASE_URL_VALUE" | sed -E 's#^https?://([^/:]+).*$#\1#')}"
HEALTH_HOST="${HEALTH_HOST:-localhost}"

echo "== Containers =="
docker compose ps

echo "== HTTP =="
curl -fsS -H "Host: ${HEALTH_HOST}" http://localhost:30888 >/dev/null
echo "OK: portal"
curl -fsS -H "Host: ${HEALTH_HOST}" http://localhost:30888/api/health/ >/dev/null
echo "OK: api health"

echo "== Redis and Celery =="
docker compose exec -T redis redis-cli ping
docker compose exec -T web celery -A config inspect ping --timeout=10

echo "== Compose =="
docker compose config >/dev/null
echo "OK: compose config"
