# Runbook: Bonvera на EC2

Хост: Amazon Linux 2023, t4g.micro (1 ГБ RAM + 2 ГБ swap), приложение в `/opt/cashback-bot`.
Контейнеры: `bot`, `db` (postgres:16), `redis`. Команды `docker compose` — из `/opt/cashback-bot`, `systemctl` — через `sudo`.

## Логи
- Приложение: `docker compose logs --tail 200 -f bot`.
- Юниты: `journalctl -u bonvera-backup -n 50 --no-pager` (так же `bonvera-restore-test`, `bonvera-watchdog`).
- Bootstrap инстанса: `/var/log/cashback-bot-bootstrap.log`.
- Общее состояние: `docker compose ps`, `systemctl list-timers 'bonvera-*'`.

## Перезапуск
```bash
docker compose restart bot                     # быстрый рестарт, образ не пересобирается
git pull && docker compose up -d --build bot   # после изменений кода
curl -s http://127.0.0.1:8080/health           # ожидаем {"ok": true}
```
Рестарт-луп: `docker compose logs --tail 100 bot`, ищем traceback до старта polling.

## Бэкап
- 03:15 UTC ежедневно: `bonvera-backup.timer` → `/opt/backups/pg-<UTC>.dump.gz` и копия в `s3://cashback-bot-backups-<account>-ap-southeast-2/YYYY/MM/`.
- Вручную: `sudo systemctl start bonvera-backup.service`, затем `journalctl -u bonvera-backup -n 20 --no-pager`. Успех — строка `backup ok size=... file=...`.
- Локально хранится 7 дней (`KEEP_DAYS`); S3 переживает инстанс.

## Restore-тест
- Вс 04:30 UTC: `bonvera-restore-test.timer`. Вручную: `sudo /opt/cashback-bot/deploy/scripts/restore-test.sh`.
- Берёт свежайший дамп из `/opt/backups` (если пусто — из S3), льёт в `cashback_restore_test`, проверяет `users`, `offers`, `apps` и непустой `alembic_version`, затем удаляет тестовую БД. Боевую не трогает.
- Итог: `journalctl -u bonvera-restore-test -n 5 --no-pager`. Успех — `restore-test ok source=... users=...`, провал — `restore-test FAILED step=<шаг>`.

## Диск и память
- Watchdog раз в 2 минуты: `/` выше 80% или свободно меньше 100 МБ → сообщение админам, не чаще раза в 6 часов.
- Состояние: `/var/lib/bonvera-watchdog.disk`, `.mem` (epoch последнего алерта), `bonvera-watchdog.fails` (счётчик `/health`).
- Руками: `df -h /`, `free -m`, `du -xh /var/lib/docker /opt/backups | sort -h | tail`.
- Чистка: `docker image prune -af`, `docker builder prune -af`, лишние `pg-*.dump.gz` в `/opt/backups`.

## OOM (бот падает и перезапускается)
1. `journalctl -k | grep -i oom` — был ли убит процесс.
2. `free -m`, `swapon --show` (swap 2 ГБ должен быть активен), `docker stats --no-stream`.
3. `docker compose restart bot`. Если повторяется — не собирать образ на хосте (`docker compose build` съедает память), собирать локально и пушить.
4. Регулярный OOM → переезд на t4g.small (пункт 5.5 плана).

## «Сеть молчит»
Алерт `📡 Сеть молчит` = заявки в PROOF/HOLD старше 24 ч, по которым не пришло ни одного postback.
1. `docker compose logs --tail 200 bot | grep -i postback` — доходят ли вызовы `/postback`.
2. Сверить `POSTBACK_SECRET` с настройками сети; партнёр должен слать на публичный HTTPS-адрес.
3. Проверить в кабинете ProCPA, уходят ли postback по этим subid.
4. Если postback'ов нет вообще и хост не видит Telegram (`curl -fsS -m 5 https://api.telegram.org`), искать проблему в сети/SG/NAT, а не в приложении.

## Таймеры
Юниты в репозитории — `deploy/systemd/`, на хосте — `/etc/systemd/system/`.
```bash
sudo cp deploy/systemd/bonvera-*.service deploy/systemd/bonvera-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bonvera-backup.timer bonvera-watchdog.timer bonvera-restore-test.timer
```
