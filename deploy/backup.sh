#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/data2/research_os}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$ROOT/backups/$STAMP"
mkdir -p "$DEST"
cd "$ROOT"

set -a
source "$ROOT/.env"
set +a

docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "$DEST/postgres.sql"
tar -czf "$DEST/storage.tar.gz" storage
cp -a docker-compose.yml .env "$DEST/"
chmod -R go-rwx "$DEST"

echo "backup=$DEST"
