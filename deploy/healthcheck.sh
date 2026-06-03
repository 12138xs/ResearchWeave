#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-${RESEARCHWEAVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"
cd "$ROOT"

echo "== Containers =="
docker compose ps

echo "== HTTP =="
curl -fsS http://localhost:30888 >/dev/null
echo "OK: portal"
curl -fsS http://localhost:30888/api/health/ >/dev/null
echo "OK: api health"

echo "== Redis and Celery =="
docker compose exec -T redis redis-cli ping
docker compose exec -T web celery -A config inspect ping --timeout=10

echo "== Compose =="
docker compose config >/tmp/research_os_compose_config_check.yml
echo "OK: compose config"
