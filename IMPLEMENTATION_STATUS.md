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

## Незавершённые задачи (этапы B–H)

- [ ] B: дизайн-система BONVERA и каркас frontend (5 вкладок + кошелёк + доп. страницы)
- [ ] C: backend API — Telegram-авторизация (initData), профиль, dashboard
- [ ] D: каталог 93 офферов — поиск/фильтры/сортировки, детали, изображения
- [ ] E: заявки, доказательства (загрузка файлов), холды, кошелёк, вывод, история
- [ ] F: 4 бонуса (+20/+100/+10/+500), рефералы, прогресс, 2 рейтинга, антинакрутка
- [ ] G: запуск Mini App из бота (кнопка /start, menu button), WebApp SDK
- [ ] H: тесты (список §21), документация, .env.example, инструкции BotFather/HTTPS

## Известные ограничения

- Production-credentials (BOT_TOKEN, ADMINS, DB, секреты, WEBAPP_URL, канал) отсутствуют в среде разработки — код интеграции реализуется, требуемые настройки фиксируются в .env.example и документации.
- Реальные партнёрские ссылки для 87 офферов должен добавить администратор.

## Следующий конкретный шаг

Запустить baseline-тесты (`pytest tests/` в .venv), зафиксировать результат, затем этап C (авторизация + API-каркас) параллельно с этапом B (каркас frontend).