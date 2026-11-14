# Развёртывание Bonvera с Supabase + Upstash Redis

Этот профиль запускает только контейнер бота. PostgreSQL и Redis работают отдельно:
- PostgreSQL: Supabase project `bonvera-production`, регион Frankfurt (`eu-central-1`).
- Redis: Upstash `bonveraredis`, регион Frankfurt, TLS/TCP.
- Сам бот должен работать на постоянном Docker-хосте (VPS/VM или постоянно работающий контейнер). Не использовать Vercel Functions или бесплатный Render Web Service для Telegram polling: процесс и APScheduler должны жить постоянно.

## Настройка .env

Скопируй `.env.example` в `.env`, затем заполни:

- `BOT_TOKEN`: новый токен от BotFather. Старый токен, ранее отправленный в чат, следует отозвать.
- `ADMINS=352509087`.
- `DB_URL`: открой Supabase Dashboard → проект `bonvera-production` → Connect → Session pooler. Возьми session-mode URL. Замени схему в начале на `postgresql+asyncpg://` (драйвер проекта — asyncpg). Не используй transaction pooler для этого постоянно работающего процесса.
- `REDIS_URL`: формат `rediss://default:<UPSTASH_PASSWORD>@helpful-labrador-96318.upstash.io:6379`. Пароль смотри в Upstash → Redis → `bonveraredis` → Connect. Не используй REST URL/REST token: aiogram RedisStorage требует Redis TCP.
- `POSTGRES_PASSWORD`: укажи тот же пароль PostgreSQL, который находится в DB_URL. Текущая проверка конфигурации требует эту переменную отдельно.
- `HASH_SALT`, `PHONE_ENCRYPTION_KEY`, `POSTBACK_SECRET`: три независимых случайных секрета по 64 hex-символа. Сгенерируй их по отдельности командой `python -c "import secrets; print(secrets.token_hex(32))"`. Не меняй `PHONE_ENCRYPTION_KEY` после начала работы и сделай его резервную копию.
- `WEB_PORT=8080`.

Файл `.env` содержит секреты. Не коммить его и не отправляй в чат.

## Запуск

В папке репозитория:

```bash
docker compose -f docker-compose.remote.yml up -d --build
docker compose -f docker-compose.remote.yml logs -f bot
```

Проверка:

```bash
curl http://127.0.0.1:8080/health
```

Ожидаемый ответ: `{"ok": true}`.

Контейнер выполняет Alembic upgrade, синхронизирует каталог и запускает Telegram polling и планировщик. В Supabase уже подготовлена схема Bonvera и запись Alembic revision `0004_offer_audit`; повторный запуск миграций должен быть no-op. При старте `seed()` загрузит 93 предложения из `catalog.yaml`.

## Публичный postback

Для партнёрских сетей опубликуй HTTPS-адрес через Caddy/Nginx reverse proxy и направь его на порт 8080. Endpoint: `GET /postback`. Значение `POSTBACK_SECRET` храни только в секретах и передавай партнёрам по защищённому каналу. До проверки реального callback не считай интеграцию работающей.

## Ограничения перед реальным запуском

- В текущем каталоге 87 предложений без партнёрского URL. Без проверенной ссылки создание сделки должно оставаться заблокированным.
- Букмекерским предложениям требуется письменное разрешение сети на выбранный cashback-трафик.
- Переводы пользователям пока подтверждаются вручную; API автоматических выплат не подключён.
- До получения нового Telegram-токена и настройки постоянного хоста polling не запустится.
