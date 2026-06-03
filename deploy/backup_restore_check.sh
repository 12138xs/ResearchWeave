#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-${RESEARCHWEAVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"
BACKUP_SQL="${2:-}"
STAMP="$(date +%Y%m%d_%H%M%S)"
RESTORE_DB="research_os_restore_check_${STAMP}"

cd "$ROOT"

set -a
source "$ROOT/.env"
set +a

if [ -z "$BACKUP_SQL" ]; then
  BACKUP_SQL="$(find "$ROOT/backups" -maxdepth 2 -type f -name postgres.sql 2>/dev/null | sort | tail -n 1 || true)"
fi

if [ -z "$BACKUP_SQL" ] || [ ! -f "$BACKUP_SQL" ]; then
  echo "ERROR: no postgres.sql backup found. Run deploy/backup.sh first or pass a backup path."
  exit 1
fi

cleanup() {
  docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "select pg_terminate_backend(pid) from pg_stat_activity where datname = '$RESTORE_DB';" >/dev/null
  docker compose exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$RESTORE_DB" >/dev/null
}
trap cleanup EXIT

echo "== Backup Restore Check =="
echo "backup=$BACKUP_SQL"
echo "restore_db=$RESTORE_DB"

docker compose exec -T postgres createdb -U "$POSTGRES_USER" "$RESTORE_DB"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$RESTORE_DB" -v ON_ERROR_STOP=1 \
  -c "create extension if not exists vector;" >/dev/null
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$RESTORE_DB" -v ON_ERROR_STOP=1 < "$BACKUP_SQL" >/tmp/research_os_restore_check.log
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$RESTORE_DB" -v ON_ERROR_STOP=1 \
  -c "select count(*) as django_users from auth_user;"

echo "restore check ok"
