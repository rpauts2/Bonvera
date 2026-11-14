# BONVERA — IMPLEMENTATION STATUS

Ветка: `feat/bonvera-mini-app-v2` (remote: https://github.com/rpauts2/Bonvera)
Последняя миграция до старта: `0004_offer_audit`
Дата начала: 2026-11-14

## Этап A — аудит (выполнен)

### Карта существующих функций

| Компонент | Назначение |
|---|---|
| `bot/__main__.py` | Запуск: validate_runtime_config → init_db (Alembic) → seed каталога → Bot+Dispatcher (RedisStorage) → aiohttp (`make_web`) → APScheduler → polling |
| `bot/config.py` | `Cfg` из env; `validate_runtime_config()` отвергает placeholder-секреты |
| `bot/db.py` | Модели: User, Bank, Offer, Tier, App, PayoutReq, RefAcc, PbLog, WalletEntry, CatalogState, DealEvent, PayoutEvent, OfferEvent. Статусы: new/proof/hold/confirmed/paid/rejected/expired. `init_db()` применяет Alembic-цепочку и шифрует legacy-телефоны |
| `bot/logic.py` | Финансовое ядро: `confirm()` (row lock, идемпотентное начисление `WalletEntry.ref=app:{id}`, реферал REF_PERCENT `ref:{id}`+RefAcc), `clawback_credit()` (сторно + заморозка выплат), `subid/parse_subid` (HMAC), `link()`, Fernet-шифрование телефонов, `bank_taken`, `hold_sum`, `notify` |
| `bot/user.py` | /start + deep-link `ref_<id>`, принятие правил 18+, гейты категорий (bk/mfo/cpl), банки→офферы→`take:` (возраст FSM, проверка `network_status=approved` для БК, обязательная партнёрская ссылка, bank_taken, MAX_ACTIVE, слоты/день, snapshot оффера), загрузка доказательств (phash-дедупликация, чек-лист), отправка комплекта, кошелёк (6 сумм), история, отмена вывода, реквизиты СБП, вывод (MIN_WITHDRAW, резерв), друзья (REF_PERCENT), поддержка |
| `bot/admin.py` | /admin: очередь скринов, ручное начисление, холд, запрос доп. данных, отказ; выплаты take/paid/reject с возвратом; история выплат; управление офферами (вкл/выкл, ссылка, ПСК МФО, согласование БК, редактирование 10 полей, примечания, чек-листы); CSV; статистика; рассылка; /reply, /ban. Аудит изменений OfferEvent; сброс согласования БК при существенных правках |
| `bot/web.py` | GET /postback (HMAC-секрет, PbLog whitelist, статусная машина OK/NO/WAIT, холд, clawback), /health; планировщик: expire броней, напоминания, hold_check |
| `bot/seed.py` | catalog.yaml → Bank/Offer/Tier; версионная синхронизация (CATALOG_VERSION), сохраняет admin-правки url/enabled |
| `bot/evidence.py`, `bot/proofs.py`, `bot/offer_rules.py`, `bot/finance_rules.py` | Чистые правила: чек-листы доказательств по категориям, прогресс/полнота комплекта, сброс согласования БК, политика clawback для выплат |
| `catalog.yaml` | 93 оффера: 16 cards, 6 bk, 52 mfo, 19 cpl |
| `alembic/versions/` | 0001_initial → 0002_offer_verification_fields → 0003_age_withdrawal_audit → 0004_offer_audit (head) |
| `tests/test_catalog.py` | 20 тестов: целостность каталога, ассеты, чек-листы, правила доказательств, clawback-политика, валидация секретов, голова Alembic |
| `assets/offers/<cat>/<code>.jpg` | 93 изображения офферов |
| Dockerfile, docker-compose*.yml, deploy/, DEPLOY_REMOTE.md | Существующая инфраструктура запуска (polling + web + scheduler) |

### Интеграционные точки для Mini App

1. `bot/web.py:make_web(bot)` — расширение существующего aiohttp-сервера: `/api/v1/*` + раздача SPA `/app`. Второй backend НЕ создаётся.
2. `bot/logic.py:confirm()` — единственная точка начисления кэшбэка; сюда встраиваются бонусы «первый заказ +10 ₽» и «10 заказов +500 ₽» (после успешного начисления, идемпотентно).
3. `bot/admin.py:paid()` (`adm:paid:`) — фиксация фактической выплаты `paid`; точка бонуса «+100 ₽ пригласившему за первую фактическую выплату друга».
4. Новая проверка подписки канала через Bot API `getChatMember` (+20 ₽, один раз), env `BONVERA_CHANNEL_ID`, `BONVERA_CHANNEL_URL`.
5. `WalletEntry` — все бонусы как проводки с уникальными `ref` и отдельными `kind`; существующая реферальная комиссия REF_PERCENT не меняется и не смешивается.
6. Новая additive-миграция `0005` — прогресс заданий/события бонусов (при необходимости); старые поля не удаляются.
7. Frontend `webapp/` (React + TypeScript + Vite + Tailwind), production-сборка внутри Docker, раздача по HTTPS существующим сервером.
8. Авторизация: серверная проверка подписи initData (HMAC по официальному алгоритму), проверка auth_date, Telegram ID только из проверенных данных; сессии с истечением.
9. Запуск TMA из бота: кнопка в /start + menu button при заданном `WEBAPP_URL`.

### Ограничения (соблюдаются)

- Только ветка `feat/bonvera-mini-app-v2`; main не трогаем, слияний нет.
- Существующие /admin, postback, планировщик, реферальная программа сохраняются.
- Миграции только additive; разрушительные изменения и очистка таблиц запрещены.
- Секреты не коммитятся; публикация без отдельного разрешения запрещена.
- 87 из 93 офферов без партнёрских ссылок: показываются, оформление заблокировано с честным пояснением.
- БК без `network_status=approved` не оформляются; возрастные ограничения проверяются на сервере.

### Baseline-тесты

- Окружение: Python 3.11.15 (venv `.venv`), зависимости из requirements.txt установлены.
- Результат до изменений: **21 passed in 0.98s** (`pytest tests/`, 2026-11-14).

## Завершённые задачи

- [x] Подключение GitHub, ветка feat/bonvera-mini-app-v2, проверка remote
- [x] Аудит кода и карта функций
- [x] Baseline-тесты: 21/21 passed
- [x] B: дизайн-система BONVERA и каркас frontend (`webapp/`)
- [x] C: backend API — initData HMAC, сессии, профиль, dashboard, rate limiting (53/53 тестов)
- [x] D+E: каталог, заявки, доказательства (приватное хранилище), кошелёк, вывод, /admin-просмотр TMA-файлов (69/69 тестов)
- [x] F: 4 бонуса (+20/+100/+10/+500), рефералы, 2 рейтинга, антинакрутка (81/81 тестов)

## Этап B — frontend-каркас (выполнен)

- Стек: React 19 + TypeScript (strict) + Vite 7 (base `/app/`), Tailwind CSS v4 (@theme-токены), framer-motion установлен, react-router-dom 7 (basename `/app`, lazy-маршруты).
- Дизайн: тёмная «премиальная игровая» финансовая тема (abyss/navy + royal/electric + gold), без маскотов и персонажей; safe-area, Telegram SDK (ready/expand/fullscreen ≥8.0, BackButton, HapticFeedback), шрифт Manrope.
- 18 маршрутов: Home (dashboard), Tasks (4 бонуса), Catalog (поиск/фильтры/сортировки), Friends (ref-ссылка, +100 и REF_PERCENT раздельно), Profile, Wallet (6 сумм), OfferPage (условия, МФО/БК-предупреждения, блокировки без ссылки/одобрения/возраста), MyApps, AppDetail (таймлайн, мультизагрузка доказательств: превью, удаление до отправки, прогресс XHR, лимиты 10 файлов/10 МБ, retry), History, Withdraw (СБП, ручной перевод, отмена), Achievements, Leaderboard (2 типа × 2 периода), Settings (СБП), Notifications, Support (FAQ), Rules (риски честно).
- API-контракт зафиксирован в `webapp/src/lib/types.ts`; клиент `api.ts` (Bearer-сессия в sessionStorage, единый JSON-конверт, обработка 401/ошибок сети), `useLoad` hook, `uploadWithProgress`.
- Авторизация клиента: initData → POST /auth/telegram; DEV-режим — вставка initData в ErrorScreen (без production-бэкдоров).
- Сборка: `npm run build` (tsc --noEmit && vite build) — **успешно**, 69 модулей, code-splitting по страницам (2026-11-14).
- Backend пока не реализован: страницы работают против контракта; данные появятся после этапа C.

## Этап C — backend API + Telegram-авторизация (выполнен)

- `bot/tma_auth.py`: официальная HMAC-SHA256-проверка initData (secret = HMAC("WebAppData", bot_token), data_check_string из отсортированных полей без `hash`), `auth_date` (свежесть ≤ 1 ч, будущее отклонено, допуск +60 с), запрет дублирующихся ключей, обязательный целый Telegram ID. Найден и исправлен timezone-баг: `datetime.utcnow().timestamp()` на не-UTC машинах сдвигал «сейчас» — заменено на `datetime.now(timezone.utc)`.
- Сессии: opaque bearer-токен (`secrets.token_urlsafe(32)`), в БД только SHA-256-хэш (`tma_sessions`), TTL `TMA_SESSION_HOURS` (24 ч), очистка истёкших при создании. Клиентский `initDataUnsafe`/Telegram ID без подписи не принимаются нигде.
- Additive-миграция `0005_tma_sessions` (down_revision `0004_offer_audit`): таблица `tma_sessions` + `users.notif_read_at`; применена в тестах на чистой sqlite через `init_db()`; тест головы Alembic обновлён.
- `bot/services.py`: общий сервисный слой (профиль, кошелёк по той же математике что и бот, каталог, заявки, задания, достижения, уведомления, друзья, meta) — TMA и бот не расходятся в деньгах/владении.
- `bot/tma_api.py`: `/api/v1` на существующем aiohttp (`make_web`), единый JSON-конверт `{ok,data|err}`; middleware: Bearer → сессия → banned 403 → 401; sliding-window rate limit (auth 20/мин на IP, API 240/мин на пользователя). Эндпоинты: auth/telegram, me, me/accept, me/age (18–120), me/sbp (Fernet + phash, маска в ответе), dashboard, meta, notifications, notifications/read; SPA `/app` + статика ассетов.
- `bot/web.py`: `setup_tma(app, bot)`, `client_max_size=25MB` под загрузку доказательств; postback/планировщик не тронуты; /health переведён на async-handler.
- Тесты: `tests/conftest.py` (изолированная sqlite + тестовые секреты до импорта bot), `tests/test_tma_auth.py` (14: валидная подпись, tamper, чужой токен, expired/future auth_date, дубликаты, отсутствие hash/user, нецелый ID, порядок полей), `tests/test_tma_api.py` (18: auth→me, 401/403, banned, изоляция пользователей, возраст/СБП-валидация и шифрование, dashboard/meta/notifications, rate limit 429, истёкшая сессия, session helpers, /health, /app).
- Результат: **53 passed** (`pytest tests/`, 2026-11-14): 21 baseline + 32 новых. Frontend-сборка этапа B не менялась.

## Этапы D+E — каталог, заявки, доказательства, кошелёк, вывод (выполнены)

- Каталог: GET /offers (поиск q, категория, сортировки reward/hold/new, available=1), GET /offers/:id (условия, МФО-реквизиты ПСК/ставка/срок/реестр, чек-листы, разрешено/запрещено), POST /offers/:id/take — серверная перепроверка всей цепочки условий бота (возраст, БК-одобрение, ссылка, bank_taken, MAX_ACTIVE, слоты/день) с машинными кодами ошибок; 87 офферов без ссылок показываются, но оформление заблокировано с честным пояснением.
- Заявки: GET /apps, GET /apps/:id (прогресс чек-листа, personal_link с HMAC-subid, таймлайн событий, can_upload/can_submit); проверка владения на каждом запросе (чужая заявка → 404).
- Доказательства: POST /apps/:id/proofs — multipart, до 10 файлов × 10 МБ, whitelist JPEG/PNG/WebP/HEIC/PDF; phash-дедупликация по тем же правилам что и бот (точная копия → 409, расстояние ≤3 → флаг ручной сверки); приватное хранилище `data/tma_proofs` (вне статики, gitignore), потоковая выдача только владельцу через авторизованный GET /apps/:id/proofs/:idx/file (Cache-Control: private, no-store); файлы бота (file_id) тоже стримятся через Bot API. POST /apps/:id/submit — полнота комплекта, защита от повторной отправки, уведомление админов.
- Кошелёк/вывод: GET /wallet (6 сумм + проводки), GET /wallet/entries, GET /withdrawals, POST /withdrawals (резерв баланса, row lock, идемпотентные проводки withdraw:{id}), POST /withdrawals/:id/cancel (возврат резерва, только pending) — механика идентична боту.
- /admin: очередь и «Все доказательства» отправляют TMA-файлы через FSInputFile наравне с Telegram file_id.
- Frontend: OfferPage — встроенный ввод возраста при age_required (PUT /me/age → повтор take), сборка успешна.
- Исправлен существующий баг HEAD: `bot/admin.py` импортировал `CAT_RU` из `bot.ui` (там его нет) — бот не запускался; теперь `CAT_RU` берётся из `bot.db` через существующий импорт. Все модули бота импортируются.
- Тесты: `tests/test_tma_deals.py` — 16 интеграционных (фильтры каталога, все гейты take, владение, загрузка/дедуп/стриминг, submit/repeat/incomplete, полный цикл кошелёк→вывод→отмена с проверкой проводок). Итог: **69 passed** (21 baseline + 48 новых).

## Этап F — бонусы, рефералы, рейтинги (выполнен)

- `bot/bonuses.py`: `grant_bonus()` — идемпотентное начисление (exists-check по уникальному `WalletEntry.ref` → row lock пользователя → banned-гейт → проводка; коммитит вызывающий). Уникальность ref — финальный барьер от гонок: при параллельных запросах второй коммит падает с IntegrityError и откатывается.
- **+10 ₽ первый заказ / +500 ₽ десятый**: `order_bonuses()` вызывается в `logic.confirm()` ДО коммита (счётчик CONFIRMED+PAID включает текущую сделку; отклонённые/отменённые/истёкшие не считаются). Refs `task:first_order:{uid}`, `task:ten_orders:{uid}`; kinds `task_first_order`/`task_ten_orders`. Бонусная строка добавлена в уведомление о подтверждении.
- **+100 ₽ за друга**: `referral_payout_bonus()` вызывается в `admin.paid()` ДО коммита — только после ПЕРВОЙ фактической выплаты друга (ровно один paid PayoutReq), реферер не забанен, не self-referral; row lock друга сериализует параллельные paid(). Ref `task:ref_bonus:{friend_id}`, kind `task_ref_bonus`, заметка БЕЗ идентификатора друга; в API-ответах ref этого kind скрыт (не раскрывает Telegram ID друга). Уведомление рефереру после коммита. Регистрация/клик/старт оффера/подтверждение сами по себе бонус не дают.
- **+20 ₽ подписка**: POST /tasks/channel/check — 409 `channel_not_configured` без BONVERA_CHANNEL_ID/URL; `getChatMember` (member/administrator/creator), ошибка Telegram → 502, не подписан → 400; начисление один раз (ref `task:channel:{uid}`), гонка параллельных проверок → IntegrityError → откат без двойного начисления; отдельный rate limit 10/мин. Ответ — обновлённый TaskState (контракт Tasks.tsx).
- REF_PERCENT не изменён: комиссия `referral` (ref `ref:{app_id}` + RefAcc) и бонус `task_ref_bonus` — разные kinds/refs, в истории раздельно (тест проверяет обе проводки).
- GET /tasks (4 постоянных задания, без ежедневных), GET /friends (ref-ссылка `/start ref_<id>`, invited/qualified, раздельные суммы комиссии и бонусов), GET /achievements (6 достижений), GET /leaderboard?type=orders|friends&period=month|all — только реальные результаты (подтверждённые заказы по reviewed_at; друзья с фактической paid-выплатой по paid_at), забаненные исключены, топ-20 + место пользователя, display только `@username` или «Участник N» — никаких Telegram ID/телефонов/имён.
- Тесты: `tests/test_tma_bonuses.py` — 12 интеграционных (+10 через полный API-цикл и повтор без начисления, +500 на 10-м и без двойного на 11-м, +100 только первая выплата/повтор/вторая выплата, guards без реферера/self/banned, сквозной хук через реальный `admin.paid()` с fake-callback, +20 один раз/не настроен/не подписан/ошибка Telegram, анонимизация и периоды обоих рейтингов, контракты tasks/friends/achievements, раздельность REF_PERCENT и +100). Обновлен кошелёк-тест D+E под реальный бонус +10 (510 ₽). Итог: **81 passed** (21 baseline + 60 новых). Frontend-сборка успешна.

## Незавершённые задачи (этапы G–H)

- [ ] G: запуск Mini App из бота (кнопка /start, menu button), .env.example, Docker multi-stage
- [ ] H: тесты (список §21), документация, инструкции BotFather/HTTPS

## Известные ограничения

- Production-credentials (BOT_TOKEN, ADMINS, DB, секреты, WEBAPP_URL, канал) отсутствуют в среде разработки — код интеграции реализуется, требуемые настройки фиксируются в .env.example и документации.
- Реальные партнёрские ссылки для 87 офферов должен добавить администратор.
- Frontend собран и типобезопасен, но ещё не проверен в реальном Telegram WebView (нет production-бота в среде разработки); проверка в Telegram — этап H после развёртывания с credentials.

## Следующий конкретный шаг

Этап G: кнопка Mini App в /start и menu button при заданном WEBAPP_URL (bot/user.py, bot/__main__.py); дополнения .env.example (WEBAPP_URL, BONVERA_CHANNEL_ID/URL, BONVERA_SUPPORT_URL, TMA_SESSION_HOURS); Dockerfile multi-stage со сборкой frontend внутри образа; инструкции BotFather/HTTPS/local dev; scripts/dev_initdata.py для локальной разработки.