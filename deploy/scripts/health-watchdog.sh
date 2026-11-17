#!/usr/bin/env bash
# Host-level watchdog: independent of the container, so a dead app can still be
# reported. Three consecutive failures of /health trigger a Telegram message to
# every id in ADMINS. Disk (/) above DISK_MAX_PCT and available memory below
# MEM_MIN_MB raise the same kind of message, throttled to one per alert kind per
# ALERT_COOLDOWN (6 h) through state files in STATE_DIR.
# Reads BOT_TOKEN/ADMINS from the same .env the app uses.
#
# Install: /opt/cashback-bot/deploy/scripts/health-watchdog.sh, chmod +x,
# systemd timer bonvera-watchdog.timer (see deploy/systemd/).
set -uo pipefail

APP_DIR="${APP_DIR:-/opt/cashback-bot}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
STATE_DIR="${STATE_DIR:-/var/lib}"
STATE_FILE="${STATE_FILE:-$STATE_DIR/bonvera-watchdog.fails}"
THRESHOLD="${THRESHOLD:-3}"
DISK_MAX_PCT="${DISK_MAX_PCT:-80}"
MEM_MIN_MB="${MEM_MIN_MB:-100}"
ALERT_COOLDOWN="${ALERT_COOLDOWN:-21600}"

mkdir -p "$STATE_DIR" "$(dirname "$STATE_FILE")"

notify_admins() {
  text="$1"
  token=$(grep -E '^BOT_TOKEN=' "$APP_DIR/.env" | cut -d= -f2- || true)
  admins=$(grep -E '^ADMINS=' "$APP_DIR/.env" | cut -d= -f2- || true)
  [ -z "$token" ] && return 0
  for id in ${admins//,/ }; do
    curl -fsS -m 10 -X POST "https://api.telegram.org/bot$token/sendMessage" \
      --data-urlencode "chat_id=$id" \
      --data-urlencode "text=$text" >/dev/null 2>&1 || true
  done
}

# 0 = quiet long enough to send again (and the timestamp is refreshed),
# 1 = the same alert already fired within ALERT_COOLDOWN, stay silent.
cooled_down() {
  file="$STATE_DIR/bonvera-watchdog.$1"
  last=$(cat "$file" 2>/dev/null || echo 0)
  case "$last" in
    ''|*[!0-9]*) last=0 ;;
  esac
  now=$(date +%s)
  if [ $((now - last)) -lt "$ALERT_COOLDOWN" ]; then
    return 1
  fi
  echo "$now" > "$file"
  return 0
}

check_health() {
  fails=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
  if curl -fsS -m 10 "$HEALTH_URL" >/dev/null 2>&1; then
    echo 0 > "$STATE_FILE"
    return 0
  fi
  fails=$((fails + 1))
  echo "$fails" > "$STATE_FILE"
  [ "$fails" -lt "$THRESHOLD" ] && return 0
  # Reset first so a long outage does not spam on every tick.
  echo 0 > "$STATE_FILE"
  notify_admins "🚨 Bonvera: /health не отвечает (${fails} проверок подряд). Хост $(hostname), $(date -u +%FT%TZ). Дальше: docker compose ps, docker compose logs --tail 100 bot"
}

check_disk() {
  used=$(df -P / | awk 'NR==2 {gsub(/%/, "", $5); print $5}')
  case "$used" in
    ''|*[!0-9]*) echo "watchdog: df unreadable, disk check skipped" >&2; return 0 ;;
  esac
  [ "$used" -lt "$DISK_MAX_PCT" ] && return 0
  cooled_down disk || return 0
  notify_admins "⚠️ Bonvera: диск / занят ${used}% (порог ${DISK_MAX_PCT}%). Хост $(hostname), $(date -u +%FT%TZ). Дальше: df -h /, du -xh /var/lib/docker /opt/backups | sort -h | tail -10, docker image prune -af"
}

check_mem() {
  avail_mb=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null)
  if [ -z "$avail_mb" ]; then
    avail_mb=$(free -m 2>/dev/null | awk '/^Mem:/ {print $7}')
  fi
  case "$avail_mb" in
    ''|*[!0-9]*) echo "watchdog: MemAvailable unreadable, memory check skipped" >&2; return 0 ;;
  esac
  [ "$avail_mb" -ge "$MEM_MIN_MB" ] && return 0
  cooled_down mem || return 0
  notify_admins "⚠️ Bonvera: свободной памяти ${avail_mb} MB (порог ${MEM_MIN_MB} MB). Хост $(hostname), $(date -u +%FT%TZ). Дальше: free -m, docker stats --no-stream, journalctl -k | grep -i oom"
}

check_health
check_disk
check_mem
