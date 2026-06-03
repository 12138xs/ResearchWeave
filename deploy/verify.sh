#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/data2/research_os}"
cd "$ROOT"

set -a
source "$ROOT/.env"
set +a

docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py bootstrap_storage >/tmp/research_os_bootstrap_storage.log
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "create extension if not exists vector;"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select extname from pg_extension where extname='vector';"
docker compose exec -T redis redis-cli ping
docker compose exec -T web celery -A config inspect ping --timeout=10
docker compose exec -T web python - <<'PY'
from config.celery import app as celery_app

checks = [
    ("fast_q", celery_app.send_task("apps.tasks.celery_tasks.fast_ping", queue="fast_q")),
    ("ai_q", celery_app.send_task("apps.tasks.celery_tasks.ai_ping", queue="ai_q")),
    ("heavy_q", celery_app.send_task("apps.tasks.celery_tasks.heavy_ping", queue="heavy_q")),
]
for name, result in checks:
    print(f"{name}: {result.get(timeout=30)}")
PY
curl -fsS http://localhost:30888/api/health/
echo
echo "verify ok"
