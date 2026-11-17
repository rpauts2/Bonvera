#!/usr/bin/env bash
# Host-level watchdog: independent of the container, so a dead app can still be
# reported. Three consecutive failures of /health trigger a Telegram message to
# every id in ADMINS. Reads BOT_TOKEN/ADMINS from the same .env the app uses.
#
# Install: /opt/cashback-bot/deploy/scripts/health-watchdog.sh, chmod +x,
# systemd timer bonvera-watchdog.timer (see deploy/systemd/).
set -uo pipefail

APP_DIR="${APP_DIR:-/opt/cashback-bot}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
STATE_FILE="${STATE_FILE:-/var/lib/bonvera-watchdog.fails}"
THRESHOLD="${THRESHOLD:-3}"

mkdir -p "$(dirname "$STATE_FILE")"
fails=$(cat "$STATE_FILE" 2>/dev/null || echo 0)

if curl -fsS -m 10 "$HEALTH_URL" >/dev/null 2>&1; then
  echo 0 > "$STATE_FILE"
  exit 0
fi

fails=$((fails + 1))
echo "$fails" > "$STATE_FILE"
[ "$fails" -lt "$THRESHOLD" ] && exit 0

# Reset first so a long outage does not spam on every tick.
echo 0 > "$STATE_FILE"

token=$(grep -E '^BOT_TOKEN=' "$APP_DIR/.env" | cut -d= -f2- || true)
admins=$(grep -E '^ADMINS=' "$APP_DIR/.env" | cut -d= -f2- || true)
[ -z "$token" ] && exit 0

text="🚨 Bonvera: /health не отвечает (${fails} проверок подряд). Хост $(hostname), $(date -u +%FT%TZ). Дальше: docker compose ps, docker compose logs --tail 100 bot"
for id in ${admins//,/ }; do
  curl -fsS -m 10 -X POST "https://api.telegram.org/bot$token/sendMessage" \
    --data-urlencode "chat_id=$id" \
    --data-urlencode "text=$text" >/dev/null 2>&1 || true
done
