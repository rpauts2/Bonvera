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

find "$BACKUP_DIR" -name 'pg-*.dump.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok size=${SIZE}B file=$TARGET.gz kept=$(find "$BACKUP_DIR" -name 'pg-*.dump.gz' | wc -l)"
