#!/usr/bin/env bash
# Nightly logical backup of the bot database.
#
#   * custom-format dump (pg_restore -Fc), gzipped on disk
#   * retention: KEEP_DAYS most recent archives
#   * fails loudly so cron mail / journal shows the problem
#
# Install: cp to /opt/cashback-bot/deploy/scripts/, chmod +x, add to /etc/cron.d.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cashback-bot}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"
MIN_BYTES="${MIN_BYTES:-10000}"
STAMP="$(date -u +%Y%m%d-%H%M)"
TARGET="$BACKUP_DIR/pg-$STAMP.dump"

mkdir -p "$BACKUP_DIR"
cd "$APP_DIR"

docker compose exec -T db pg_dump -U cashback -d cashback -Fc > "$TARGET.part"
SIZE=$(wc -c < "$TARGET.part")
if [ "$SIZE" -lt "$MIN_BYTES" ]; then
  echo "backup failed: dump is only ${SIZE}B" >&2
  rm -f "$TARGET.part"
  exit 1
fi

mv "$TARGET.part" "$TARGET"
gzip -f "$TARGET"

# Offsite copy: the local archive dies with the instance, S3 survives it.
REGION="${AWS_REGION_NAME:-ap-southeast-2}"
if command -v aws >/dev/null 2>&1; then
  ACCOUNT=$(aws sts get-caller-identity --region "$REGION" --query Account --output text 2>/dev/null || true)
  if [ -z "$ACCOUNT" ]; then
    echo "s3 upload skipped: no instance credentials" >&2
  else
    BUCKET="${BACKUP_BUCKET:-cashback-bot-backups-${ACCOUNT}-${REGION}}"
    KEY="$(date -u +%Y/%m)/$(basename "$TARGET.gz")"
    if aws s3 cp "$TARGET.gz" "s3://$BUCKET/$KEY" --region "$REGION" --only-show-errors; then
      echo "uploaded s3://$BUCKET/$KEY"
    else
      echo "s3 upload failed for $TARGET.gz" >&2
      exit 1
    fi
  fi
fi

find "$BACKUP_DIR" -name 'pg-*.dump.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok size=${SIZE}B file=$TARGET.gz kept=$(find "$BACKUP_DIR" -name 'pg-*.dump.gz' | wc -l)"
