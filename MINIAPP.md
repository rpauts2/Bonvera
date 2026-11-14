# BONVERA Mini App — запуск и настройка

Mini App работает внутри **существующего** процесса бота: aiogram polling + aiohttp
(`/api/v1/*`, SPA на `/app`, postback `/postback`) + APScheduler. Второго backend нет.
Frontend (`webapp/`, React + TypeScript + Vite) собирается в `webapp/dist` и раздаётся
тем же aiohttp-сервером по адресу `https://<домен>/app`.

## 1. BotFather

1. Возьми токен бота (`/mybots` → API Token) → `BOT_TOKEN` в `.env`.
2. `/mybots` → выбери бота → **Bot Settings → Menu Button → Configure menu button**:
   - URL: `https://<домен>/app` (тот же, что `WEBAPP_URL`).
   - Приложение также само вызывает `set_chat_menu_button` при старте, если задан `WEBAPP_URL`.
3. **Bot Settings → Main Mini App**: укажи `https://<домен>/app` — это даст запуск
   из профиля бота и кнопку в шапке чата.
4. Домен должен быть подтверждён в BotFather (`/setdomain` не требуется для web_app,
   но Main Mini App требует HTTPS-домен, который ты контролируешь).

Кнопка «📱 Открыть BONVERA» в `/start` — **inline** `web_app`-кнопка: Telegram
подписывает `initData` для этого пути запуска. Reply-keyboard `web_app`-кнопка
намеренно НЕ используется: она открывает приложение с пустым `initData`, и
серверная авторизация невозможна.

## 2. HTTPS

Telegram открывает Mini App только по HTTPS. Варианты:

- **Reverse proxy** (nginx/Caddy/Traefik) на том же хосте: TLS-терминация и
  `proxy_pass http://127.0.0.1:8080`. Сертификат — Let's Encrypt.
- Готовый профиль развёртывания: `DEPLOY_REMOTE.md` (Docker-хост + Supabase + Upstash).

Пример nginx:

```nginx
server {
    listen 443 ssl;
    server_name bonvera.example.com;
    ssl_certificate     /etc/letsencrypt/live/bonvera.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bonvera.example.com/privkey.pem;
    client_max_body_size 25m;   # загрузка доказательств: до 10 файлов × 10 МБ
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

`WEBAPP_URL=https://bonvera.example.com/app` — без завершающего слэша.
Пока `WEBAPP_URL` пуст, кнопка приложения и menu button не показываются,
бот работает в обычном текстовом режиме.

## 3. Локальная разработка

```bash
# backend (Python 3.11)
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
cp .env.example .env   # заполни BOT_TOKEN, ADMINS, секреты (см. DEPLOY_REMOTE.md)
.venv/Scripts/python -m bot          # aiohttp на :8080 + polling

# frontend (Node 20.19+/22.12+)
cd webapp && npm ci && npm run dev   # Vite на :5173, proxy /api → :8080
```

Открой `http://localhost:5173/app/` в обычном браузере (вне Telegram). Появится
экран ошибки входа с DEV-полем. Сгенерируй подписанный initData и вставь его:

```bash
python scripts/dev_initdata.py 12345 dev_user
```

Скрипт читает `BOT_TOKEN` из `.env`/окружения и подписывает initData официальным
HMAC-алгоритмом — локальный backend принимает его как настоящий запуск Telegram.
DEV-поле показывается только в `import.meta.env.DEV` и только вне Telegram;
в production-сборке его нет.

Тесты: `.venv/Scripts/python -m pytest tests/` (изолированная sqlite, без сети).

## 4. Production-сборка

Dockerfile — multi-stage: Node 24 собирает `webapp/dist`, Python 3.11 запускает бота;
dist копируется в образ и раздаётся на `/app`.

```bash
docker compose -f docker-compose.remote.yml up -d --build
docker compose -f docker-compose.remote.yml logs -f bot
```

Один долгоживущий процесс (polling + web + scheduler). Не переносить polling в
Vercel Functions/serverless: APScheduler и postback должны жить постоянно.

## 5. Канал и бонус +20 ₽

```env
BONVERA_CHANNEL_ID=-1001234567890   # или @username
BONVERA_CHANNEL_URL=https://t.me/your_channel
```

Бот должен быть участником канала (достаточно прав на чтение участников;
`getChatMember` работает и без админки, если канал публичный или бот добавлен).
Пока обе переменные пусты, задание показывается с честным пояснением
«Канал пока не настроен», начисление недоступно (409 `channel_not_configured`).

## 6. Безопасность (что уже реализовано)

- `initData` проверяется на сервере: HMAC-SHA256 (`WebAppData` + bot token),
  `auth_date` ≤ 1 ч, запрет дублирующихся ключей, целый Telegram ID.
  `initDataUnsafe` и клиентский Telegram ID нигде не используются для авторизации.
- Сессии: opaque bearer-токен, в БД только SHA-256-хэш, TTL `TMA_SESSION_HOURS`.
- Все деньги — на сервере: row locks, идемпотентные проводки `WalletEntry`
  с уникальными `ref`, транзакции. Клиент только отображает.
- Бонусы: +20 подписка (один раз), +10 первый заказ, +500 десятый,
  +100 рефереру только после первой фактической выплаты друга. REF_PERCENT —
  отдельная комиссия, не смешивается с бонусами.
- Доказательства: приватное хранилище вне статики, выдача только владельцу
  через авторизованный стриминг; phash-дедупликация.
- Rate limiting: auth 20/мин на IP, API 240/мин на пользователя, проверка
  подписки 10/мин.

## 7. Чек-лист перед публикацией

- [ ] `BOT_TOKEN`, `ADMINS`, `DB_URL`, `REDIS_URL` заполнены реальными значениями.
- [ ] `HASH_SALT`, `PHONE_ENCRYPTION_KEY`, `POSTBACK_SECRET` — случайные ≥ 32 символов;
      `PHONE_ENCRYPTION_KEY` сохранён в резервной копии и НЕ меняется после запуска.
- [ ] HTTPS-домен настроен, `WEBAPP_URL` указывает на `/app`.
- [ ] Menu Button и Main Mini App настроены в BotFather.
- [ ] `BONVERA_CHANNEL_ID`/`BONVERA_CHANNEL_URL` заданы (или бонус честно недоступен).
- [ ] Партнёрские ссылки добавлены администратором через /admin (87 из 93 офферов
      без ссылок показываются, но оформление заблокировано).
- [ ] `pytest tests/` зелёный; `npm run build` успешен.
- [ ] Публикация приложения — только с отдельного разрешения владельца.