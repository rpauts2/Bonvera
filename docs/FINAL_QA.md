# Итоговая проверка BONVERA (бот + Telegram Mini App)

Дата проверки: 14.11.2026
Ветка: `feat/bonvera-mini-app-v2` → `https://github.com/rpauts2/Bonvera`

## 1. Что проверено автоматически

| Проверка | Команда | Результат |
|---|---|---|
| Backend | `python -m pytest tests/` | **90 passed** |
| Frontend | `cd webapp && npm test` | **55 passed** |
| Сборка frontend | `cd webapp && npm run build` (`tsc --noEmit && vite build`) | успешно, 69 модулей |
| Alembic | тест головы ревизии | одна голова, цепочка `0001 → 0005_tma_sessions` |
| Каталог | `tests/test_catalog.py` | 93 оффера: 16 карт, 6 букмекеров, 52 МФО, 19 CPL |
| Ассеты | `tests/test_catalog.py` | 93 уникальных JPG, SHA-256 всех файлов различны |
| Импорты бота | smoke-импорт всех модулей `bot/` | без ошибок (исправлен баг `CAT_RU` в `bot/admin.py`) |

## 2. Матрица покрытия §21 (backend)

| Требование §21 | Тест |
|---|---|
| Проверка Telegram initData | `tests/test_tma_auth.py::test_valid_signature_passes` |
| Истёкшая авторизация | `test_tma_auth.py::test_expired_auth_date_rejected`, `test_tma_api.py::test_auth_rejects_expired_init_data` |
| Неверная подпись | `test_tma_auth.py::test_tampered_field_rejected`, `test_tma_api.py::test_auth_rejects_bad_signature` |
| Чужой токен бота | `test_tma_auth.py::test_foreign_bot_token_rejected` |
| Дублирующиеся поля / отсутствие hash / нецелый ID | `test_tma_auth.py` (5 тестов) |
| Доступ к чужой заявке | `tests/test_tma_deals.py::test_apps_ownership_isolation` |
| Создание сделки | `test_tma_deals.py::test_take_full_flow` |
| Запрет сделки без партнёрской ссылки | `test_tma_deals.py::test_take_no_link_blocked` |
| Запрет несогласованного букмекерского оффера | `test_tma_deals.py::test_take_bk_approval_gate` |
| Возрастные ограничения | `test_tma_deals.py::test_take_age_gate`, `test_tma_api.py::test_accept_and_age_validation` |
| Повторная проверка подписки | `tests/test_tma_bonuses.py::test_channel_bonus_once` |
| Начисление +20 ₽ | `test_tma_bonuses.py::test_channel_bonus_once`, `::test_channel_not_subscribed`, `::test_channel_telegram_error` |
| Начисление +100 ₽ за первую выплату другу | `test_tma_bonuses.py::test_referral_bonus_first_paid_only`, `::test_referral_bonus_guards`, `::test_admin_paid_hook_end_to_end` |
| Начисление +10 ₽ за первый заказ | `test_tma_bonuses.py::test_first_order_bonus_via_api` |
| Начисление +500 ₽ за десятый заказ | `test_tma_bonuses.py::test_ten_orders_bonus_no_double` |
| Повторные запросы | `test_tma_deals.py::test_proof_submit_and_repeat`, `test_tma_bonuses.py` |
| Одновременные запросы | `tests/test_tma_hardening.py::test_concurrent_confirm_single_credit`, `::test_concurrent_channel_checks_single_credit` |
| Повторный postback | `test_tma_hardening.py::test_postback_approved_hold_and_repeat`, `::test_postback_rejected_clawback_once`, `::test_postback_hold_idempotent_then_approved` |
| Валидация postback | `test_tma_hardening.py::test_postback_auth_and_validation` |
| Корректный баланс | `test_tma_deals.py::test_wallet_withdrawal_cancel_cycle` |
| Запрос вывода | `test_tma_deals.py::test_wallet_withdrawal_cancel_cycle`, `::test_withdrawal_requires_phone` |
| История операций | `test_tma_bonuses.py::test_referral_commission_separate_from_bonus` |
| Права администратора | `test_tma_hardening.py::test_admin_rights_paid_and_confirm` |
| Загрузка доказательств | `test_tma_deals.py::test_proof_upload_dedup_and_stream` |
| Работа API с тестовой БД | `tests/conftest.py` — изолированная sqlite + Alembic на чистой схеме |
| Запуск Mini App из бота | `tests/test_bot_launch.py` (2 теста) |

## 3. Матрица покрытия §21 (frontend)

npm-реестр недоступен из этой среды (прокси отклоняет соединение), поэтому vitest/jsdom установить не удалось. Тесты выполняются на уже установленном toolchain: проектный **Vite в SSR-режиме + `react-dom/server` + встроенный `node --test`** (`webapp/tests/`). Проверяется настоящий код приложения, не копия.

| Требование §21 | Тест |
|---|---|
| Сборка | `npm run build` — `tsc --noEmit` строгий, ошибок нет |
| Проверка навигации | `tests/navigation.test.mjs` — загрузочный экран, нижняя панель из 5 вкладок, все 17 маршрутов рендерят свой экран, внутренние страницы не дублируют панель |
| Формы | `tests/validation.test.mjs` — 10 правил формы вывода (сумма, минимум, доступный баланс, банк, телефон, запятая как разделитель) |
| Состояние загрузки | `tests/navigation.test.mjs` (скелетон на boot-экране), `tests/components.test.mjs` |
| Ошибки API | `tests/api.test.mjs` (типизированный `ApiError`, код/статус/сообщение, 401 → сброс сессии, сетевая ошибка) |
| Адаптивность и safe area | `tests/components.test.mjs` + `tests/navigation.test.mjs` — `safe-area-inset-top/bottom`, `overscroll-behavior-y: none`, `min-height: 100vh`, ширина контейнера `max-w-[520px]` |
| Telegram WebView | `tests/telegram.test.mjs` — `ready/expand`, цвета темы, `requestFullscreen` только на ≥ 8.0, нативные диалоги только на ≥ 6.2 с откатом на `window.alert/confirm`, открытие `t.me` через клиент Telegram |
| Пустые данные | `tests/components.test.mjs` — `EmptyState` с понятным текстом, оффер без ссылки помечен «Нет ссылки», а не скрыт |
| Реальные данные | `tests/components.test.mjs` — карточка оффера показывает бренд, продукт, награду, холд и ведёт на `/offer/:id`; бейджи всех 7 статусов заявки |

## 4. Исправления финансовых сценариев

- При отзыве лида ожидающие запросы на вывод отменяются и резервируется/возвращается ровно одна компенсирующая проводка.
- Уже обрабатываемые выводы переводятся в `review_required`; администратор сверяет факт банковского перевода и только затем отмечает выплату либо отклоняет запрос с возвратом.
- Повторное подтверждение одной сделки защищено блокировкой строки и уникальным ключом финансовой проводки (`WalletEntry.ref`); при гонке второй запрос откатывается и возвращает `False` — двойного начисления нет.
- Окончание холда не начисляет деньги автоматически: администратор получает одно уведомление и выполняет финальную проверку.
- Запрос дополнительных доказательств требует нового файла, загруженного после запроса.
- Существенное изменение ссылки/условий/выплаты/холда букмекера сбрасывает письменное согласование.
- Изменения каталога пишутся в отдельный журнал с администратором и временем; реальные affiliate URL-токены не копируются в текст аудита.

## 5. Доказательства по типу оффера

- Карты: личный кабинет/карточный продукт с ФИО для сверки и выпуском/активацией; если ЦД содержит покупку или расход — отдельная операция с датой, суммой и торговой точкой; для платного выпуска — отдельное подтверждение оплаты.
- МФО: два обязательных файла — ЛК с полным ФИО и статусом «Одобрено», затем подтверждение фактической выдачи с датой и суммой. Одобрение без перечисления займа не подтверждает ЦД «выдача займа».
- БК: профиль с идентификацией, история депозитов и рассчитанная квалифицирующая ставка; если конкретная акция отдельно требует начисления фрибета, потребуется дополнительный экран его начисления.
- CPL: подтверждение принятой/валидной заявки или привязки карты по ЦД. Само оформление займа не требуется, если ЦД этого не говорит.

Во всех чек-листах указано скрывать паспортные сведения, дату рождения, адрес, телефон, полные платёжные реквизиты, номера договоров и любые коды. Бот и Mini App не просят CVV/CVC, PIN, пароль, OTP/SMS-код, фото всей карты, паспорт или полный договор займа. ФИО остаётся видимым только на том подтверждении, где нужна сверка владельца.

## 6. Не проверено в этой среде

- Production-credentials (BOT_TOKEN, ADMINS, DB_URL, REDIS_URL, секреты, WEBAPP_URL, канал) отсутствуют: нельзя проверить реальный polling, применение Alembic на PostgreSQL, выдачу файлов из Telegram, реальные банковские переводы и работу внутри живого Telegram WebView.
- Docker недоступен: образ multi-stage проверен структурно и той же командой сборки frontend, что выполняется в образе, но сам образ не собирался.
- Telegram WebView проверен только через SDK-стабы: поведение конкретной версии клиента (тема, клавиатура, сворачивание, аппаратная кнопка «Назад») вживую не наблюдалось.
- Внешние партнёрские сети: postback проверен на синтетическом HMAC-секрете, реальные форматы сетей не подтверждены.
- npm-реестр недоступен → визуальная регрессия (скриншоты, реальный рендер в браузере) и e2e-сценарии в реальном WebView не автоматизированы.

## 7. Оставшиеся бизнес-зависимости

- В пользовательском списке URL есть только у 6 БК; для остальных 87 офферов ссылки должны быть добавлены администратором. Без ссылки бот и Mini App блокируют создание сделки.
- Все 6 БК должны получить письменное разрешение рекламодателя/сети на cashback-формат и конкретный источник трафика; только после этого оффер переводится в согласованный статус.
- Автоматические выплаты по API не подключены; сейчас администратор вручную подтверждает фактический перевод (Mini App честно сообщает об этом на экране вывода).
- Проверка возраста — само-декларация (количество полных лет), не документальная идентификация.
- Скриншотные доказательства содержат персональные/финансовые данные. Нужны политика хранения и удаления, ограничение доступа администраторов и срок хранения файлов.
