#!/usr/bin/env bash
# Weekly restore drill: take the newest dump (local /opt/backups first, S3 as a
# fallback), load it into a scratch database inside the same container, check
# that the schema and the core tables are readable, then drop the scratch
# database. The live database is never written to.
#
# Install: /opt/cashback-bot/deploy/scripts/restore-test.sh, chmod +x,
# systemd timer bonvera-restore-test.timer (see deploy/systemd/).
#
# Exit 0 = the newest dump restores and passes the checks. Anything else = the
# drill failed; the journal holds one summary line naming the failing step.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cashback-bot}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
MAIN_DB="${MAIN_DB:-cashback}"
RESTORE_DB="${RESTORE_DB:-cashback_restore_test}"
DB_USER="${DB_USER:-cashback}"
REGION="${AWS_REGION_NAME:-ap-southeast-2}"
MIN_BYTES="${MIN_BYTES:-512}"
STARTED=$SECONDS
STEP="init"
SOURCE="none"
TMP_DUMP=""
DROPPED=0

log() { printf '%s restore-test %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "FAILED step=$STEP: $*"; exit 1; }

# Nothing but the scratch database is ever created, and it never survives a run.
cleanup() {
  rc=$?
  if [ "$DROPPED" -eq 0 ] && [ -d "$APP_DIR" ]; then
    ( cd "$APP_DIR" && docker compose exec -T db psql -U "$DB_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\" WITH (FORCE)" >/dev/null 2>&1 ) || true
  fi
  if [ -n "$TMP_DUMP" ]; then
    rm -f "$TMP_DUMP"
  fi
  exit "$rc"
}
trap cleanup EXIT

# The scratch name ends up in SQL, so keep it boring and never point it at prod.
case "$RESTORE_DB" in
  ''|*[!a-z0-9_]*) die "RESTORE_DB must use lowercase letters, digits and underscore" ;;
esac
if [ "$RESTORE_DB" = "$MAIN_DB" ]; then
  die "RESTORE_DB equals MAIN_DB ($MAIN_DB), refusing to run"
fi

STEP="select-dump"
[ -d "$APP_DIR" ] || die "$APP_DIR is missing"
[ -d "$BACKUP_DIR" ] || mkdir -p "$BACKUP_DIR" || true

local_dump=""
if [ -d "$BACKUP_DIR" ]; then
  local_dump=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'pg-*.dump.gz' -printf '%T@ %p\n' \
    2>/dev/null | sort -n | tail -n 1 | cut -d ' ' -f 2- || true)
fi

if [ -n "$local_dump" ]; then
  dump="$local_dump"
  SOURCE="local:$dump"
else
  STEP="fetch-s3"
  command -v aws >/dev/null 2>&1 || die "no local dumps in $BACKUP_DIR and no aws CLI"
  account=$(aws sts get-caller-identity --region "$REGION" --query Account --output text 2>/dev/null || true)
  [ -n "$account" ] || die "no local dumps in $BACKUP_DIR and no instance credentials"
  bucket="${BACKUP_BUCKET:-cashback-bot-backups-$account-$REGION}"
  key=$(aws s3 ls "s3://$bucket" --recursive --region "$REGION" 2>/dev/null \
    | sort -k1,2 | tail -n 1 | awk '{print $4}' || true)
  [ -n "$key" ] || die "no local dumps and no objects in s3://$bucket"
  TMP_DUMP=$(mktemp "${TMPDIR:-/tmp}/bonvera-restore.XXXXXX.dump.gz")
  aws s3 cp "s3://$bucket/$key" "$TMP_DUMP" --region "$REGION" --only-show-errors \
    || die "download failed: s3://$bucket/$key"
  dump="$TMP_DUMP"
  SOURCE="s3://$bucket/$key"
fi

size=$(wc -c < "$dump" | tr -d ' ')
[ "$size" -ge "$MIN_BYTES" ] || die "dump $SOURCE is only ${size}B, probably truncated"

STEP="create-db"
( cd "$APP_DIR" && docker compose exec -T db psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\" WITH (FORCE)" \
    -c "CREATE DATABASE \"$RESTORE_DB\"" >/dev/null ) || die "cannot create $RESTORE_DB"

STEP="restore"
gunzip -c "$dump" | ( cd "$APP_DIR" && docker compose exec -T db pg_restore -U "$DB_USER" \
    -d "$RESTORE_DB" --no-owner --no-privileges --single-transaction >/dev/null ) \
  || die "pg_restore rejected $SOURCE"

STEP="verify"
counts=$( cd "$APP_DIR" && docker compose exec -T db psql -U "$DB_USER" -d "$RESTORE_DB" -tA \
    -v ON_ERROR_STOP=1 \
    -c "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM offers), (SELECT count(*) FROM apps), (SELECT count(*) FROM alembic_version)" \
    2>&1 ) || die "schema unreadable in $RESTORE_DB: $counts"

IFS='|' read -r n_users n_offers n_apps n_alembic <<< "$counts"
for pair in "users:$n_users" "offers:$n_offers" "apps:$n_apps" "alembic_version:$n_alembic"; do
  name="${pair%%:*}"
  value="${pair##*:}"
  case "$value" in
    ''|*[!0-9]*) die "unexpected count for $name: '$value'" ;;
  esac
  [ "$value" -gt 0 ] || die "$name is empty in the restored dump"
done

STEP="drop"
( cd "$APP_DIR" && docker compose exec -T db psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\" WITH (FORCE)" >/dev/null ) \
  || die "restored data is fine but dropping $RESTORE_DB failed"
DROPPED=1

log "ok source=$SOURCE users=$n_users offers=$n_offers apps=$n_apps alembic=$n_alembic scratch_db=$RESTORE_DB dropped=yes duration=$((SECONDS - STARTED))s"
