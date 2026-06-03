#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/data2/research_os}"
SMOKE_STATUS="skipped"
DEFAULT_MEMBER_USERNAMES="lirongzu tankaiyao wangbuxuan zhangchaochong cenjianhuan liumenghan tanliqin wangxiean zqs chenliao lizongze pengguohang tansiyi"
MEMBER_USERNAMES="${RESEARCH_OS_MEMBER_USERNAMES:-$DEFAULT_MEMBER_USERNAMES}"

cd "$ROOT"

echo "== Trial Readiness: Health =="
bash "$ROOT/deploy/healthcheck.sh" "$ROOT"

echo "== Trial Readiness: Trial Accounts Dry Run =="
docker compose exec -T web python manage.py bootstrap_trial_accounts --dry-run

echo "== Trial Readiness: Member Accounts Dry Run =="
docker compose exec -T web python manage.py bootstrap_member_accounts --dry-run --usernames "$MEMBER_USERNAMES"

echo "== Trial Readiness: Backup =="
backup_output="$(bash "$ROOT/deploy/backup.sh" "$ROOT")"
echo "$backup_output"
backup_dir="$(echo "$backup_output" | awk -F= '/^backup=/{print $2}')"
if [ -z "$backup_dir" ] || [ ! -f "$backup_dir/postgres.sql" ]; then
  echo "ERROR: backup did not create postgres.sql"
  exit 1
fi
bash "$ROOT/deploy/backup_restore_check.sh" "$ROOT" "$backup_dir/postgres.sql"

echo "== Trial Readiness: Resource Snapshot =="
df -h "$ROOT"
free -h
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"

echo "== Trial Readiness: Trial Smoke =="
if [ -n "${RESEARCH_OS_SMOKE_USERNAME:-}" ] && [ -n "${RESEARCH_OS_SMOKE_PASSWORD:-}" ]; then
  bash "$ROOT/deploy/trial_smoke_check.sh"
  SMOKE_STATUS="ok"
else
  echo "SKIP: trial smoke check (set RESEARCH_OS_SMOKE_USERNAME and RESEARCH_OS_SMOKE_PASSWORD)"
fi

echo "== Trial Readiness: Report =="
report_dir="$ROOT/docs/operations/trial-reports"
mkdir -p "$report_dir"
report_path="$report_dir/trial-readiness-$(date +%Y%m%d_%H%M%S).md"
docker compose exec -T web python manage.py generate_trial_report \
  --output - \
  --backup-dir "$backup_dir" \
  --restore-status "ok" \
  --smoke-status "$SMOKE_STATUS" \
  --member-usernames "$MEMBER_USERNAMES" \
  --resource-snapshot "captured by deploy/trial_readiness.sh" > "$report_path"
echo "trial_report=$report_path"

echo "trial readiness ok"
