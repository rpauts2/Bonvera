# VK MFO Outreach — проектное решение

**Дата:** 2026-11-22  
**Репозиторий:** `rpauts2/Bonvera`  
**Базовая ветка:** `feat/bonvera-mini-app-v2`  
**Рабочая ветка:** `feat/vk-mfo-outreach`

## 1. Цель

Добавить в Bonvera самостоятельный VK-канал привлечения и обработки лидов по предложениям МФО. Это не второй независимый продукт: VK использует существующие PostgreSQL, Alembic, aiohttp backend, Telegram-админку/Mini App и общую CPA-аналитику, но хранит VK-идентичность отдельно от Telegram-пользователей.

Целевой пользовательский путь:

1. Пользователь видит рекламное объявление VK и нажимает «Начать» / «Написать».
2. Он сам открывает диалог с сообществом Bonvera.
3. VK-бот приветствует пользователя и объясняет, зачем запрашивается телефон.
4. Пользователь отдельно подтверждает обработку персональных данных и отправляет номер.
5. Бот показывает четыре настраиваемых прямых предложения МФО и пятый пункт — внешнюю CPA-витрину Bonvera.
6. Каждый переход проходит через собственный tracking redirect Bonvera.
7. В админке видны контакты и действующие согласия, кампании, отправки, клики, источники и доступные подтверждённые конверсии.

## 2. Зафиксированные требования владельца

- Канал: ВКонтакте.
- Аудио нет. Рекламные сообщения текстовые.
- Внешняя рекламная подача ведёт в диалог VK-бота через CTA «Начать».
- Внутри бота пользователь сначала проходит согласие на обработку персональных данных и вводит телефон.
- Затем показываются ровно четыре прямых предложения МФО и пятый пункт — внешняя ссылка на CPA-витрину, которую владелец добавит самостоятельно.
- Администратор должен управлять четырьмя ссылками, пятой ссылкой, текстами, кампаниями, списками контактов и статистикой.
- Нужны импорт разрешённого списка контактов и инструменты привлечения новой аудитории.
- Никаких выдуманных CPA URL, названий, сумм, условий или статусов одобрения.
- Никаких изменений `main`, production или действующих данных в рамках разработки.

## 3. Цели

- Реальный VK community bot на официальном VK API.
- Отдельная VK-идентичность, не смешанная с Telegram ID.
- Удобная воронка «сообщение → согласие → телефон → пять ссылок».
- Редактируемые offer slots 1–4 и storefront slot 5.
- Click tracking для каждого слота, пользователя и кампании.
- Админ-панель VK Marketing внутри существующей Bonvera admin.
- Импорт контактов только с проверяемыми сведениями о предварительном согласии на рекламу.
- Очередь рассылок с возобновлением после перезапуска, статусами, ограничением частоты, отменой и отчётом.
- Привлечение новых пользователей через официальные рекламные инструменты VK, а не сканирование личных профилей.
- Возможность расширить VK-контур новыми CPA-партнёрами без переписывания бота.

## 4. Не-цели и запреты

- Не реализовывать парсинг/скрейпинг VK-профилей, сбор ID участников чужих сообществ, перебор пользователей, обход ограничений VK или холодную массовую рассылку незнакомым людям.
- Не отправлять рекламу в личку людям только потому, что администратор загрузил их VK ID. Для рекламной отправки нужны одновременно зафиксированное предварительное согласие на рекламу и разрешение VK на сообщения сообщества.
- Не таргетировать людей по предположениям о долгах, просрочках, плохой кредитной истории или иной чувствительной финансовой уязвимости. Новую аудиторию привлекать официальной рекламой с допустимым контекстным/широким таргетингом.
- Не обещать «одобряем всем», «100% одобрение», «вам одобрен займ» или «предодобрен» без персонального подтверждения от конкретной МФО. Статическое рекламное сообщение не является решением кредитора.
- Не отправлять телефон пользователя МФО автоматически. Передавать его партнёру можно только при отдельном правовом основании, информировании и явно предусмотренном сценарии/интеграции. В первой версии телефон хранится в Bonvera и не добавляется в CPA URL.
- Не хранить токены VK, API secrets, ключи или пароли в Git.
- Не отправлять реальные рассылки до отдельной настройки сообщества, проверки согласий и ручного включения кампании администратором.

## 5. Подходы и выбранная архитектура

### Подход A — отдельный второй backend и отдельная БД
Не выбран: дублирует пользователей, финансы, аналитику, мониторинг и администрирование.

### Подход B — VK как канал существующего Bonvera backend
**Выбран.** Новые VK-модули подключаются к текущему aiohttp приложению. PostgreSQL/Alembic остаются единственным хранилищем. Telegram-бот продолжает работать независимо. VK callback endpoint, клиент VK API, модели VK, кампании и админские API добавляются отдельными модулями.

### Подход C — SaaS-конструктор чат-ботов
Не выбран для ядра: пользовательские данные, CPA click tracking, история согласий и конверсии всё равно должны синхронизироваться с Bonvera, а зависимость от стороннего SaaS усложнит контроль и стоимость.

## 6. Пользовательская воронка VK

### 6.1 Старт диалога

Пользователь должен сам инициировать диалог: перейти в сообщество из официальной VK-рекламы, открыть чат и нажать «Начать» либо отправить сообщение.

Бот отвечает приветствием и коротко описывает сервис. Из рекламного объявления не следует делать вывод о том, что кредит уже одобрен.

Сохраняются:
- VK user ID;
- минимальные данные профиля, полученные из callback;
- дата первого обращения;
- источник/кампания, если подтверждённо передан campaign ref;
- дата последнего сообщения.

### 6.2 Согласие и телефон

Перед сбором телефона бот показывает отдельное уведомление:
- кто является оператором персональных данных;
- для какой цели нужен телефон;
- где находится политика конфиденциальности;
- срок хранения;
- как отозвать согласие/запросить удаление.

Согласие на обработку персональных данных — отдельное явное действие, не объединённое с согласием на рекламу.

Телефон вводится пользователем в диалоге. Backend:
- нормализует номер;
- валидирует российский формат;
- сохраняет телефон только в шифрованном виде через существующие `phone_encrypt` / `phone_decrypt`;
- сохраняет поисковый хеш через существующий `phash`;
- не пишет номер в логи, события, ошибки и URL;
- не принимает номера до фиксации согласия.

Согласие на будущие рекламные сообщения — отдельное, необязательное действие. Отказ от рекламных сообщений не блокирует показ пяти ссылок и использование бота. Фиксировать текст/версию согласия, дату, VK user ID, событие, источник и факт действия пользователя.

### 6.3 Пять ссылок

После ввода телефона показывается фиксированный список:
1. МФО №1 — настраиваемое имя и HTTPS URL.
2. МФО №2 — настраиваемое имя и HTTPS URL.
3. МФО №3 — настраиваемое имя и HTTPS URL.
4. МФО №4 — настраиваемое имя и HTTPS URL.
5. «Все предложения / Витрина Bonvera» — внешний HTTPS URL из CPA-кабинета владельца.

Пятый URL пуст до ввода владельцем. Нельзя подставлять демонстрационный, чужой или сгенерированный адрес. Каждый слот можно отключить, но пункт витрины не должен показываться, пока URL не настроен.

Для каждого слота настраиваются: название рекламодателя, короткая подпись, URL, tracking-параметр (если CPA-сеть его поддерживает), активность, порядок и дата последней проверки. Партнёрские URL хранятся отдельно от кода и не выводятся в открытые логи.

### 6.4 Click tracking

Все ссылки показываются пользователю как ссылки на внутренний редирект:
- `GET /vk/go/{opaque_token}`
- сервер проверяет токен;
- записывает VK contact, slot, campaign, источник и timestamp;
- редиректит на указанный внешний URL;
- если для слота задан согласованный CPA tracking parameter, добавляет уникальный click token именно в этот параметр;
- никогда не добавляет номер телефона или VK ID в ссылку.

Клик учитывается даже без postback. Конверсия/комиссия отмечается только при получении реального postback/API/отчёта от CPA-партнёра. Число кликов нельзя отображать как число одобренных заявок.

## 7. Рекламные кампании и аудитории

### 7.1 Создание кампании

Поля кампании:
- internal name;
- рекламный текст;
- CTA;
- рекламодатель (юридическое наименование/идентификация);
- обязательные предупреждения;
- ERID/поля маркировки, когда применимо;
- дата и время старта/окончания;
- источник/utm campaign;
- целевая аудитория;
- статус: draft, preview, scheduled, running, paused, completed, cancelled, failed.

До запуска админ видит предпросмотр, размер аудитории, причины исключения контактов и отдельное подтверждение.

### 7.2 Проверка рекламных утверждений

Шаблоны могут сообщать о доступном предложении и максимальной сумме, если она соответствует утверждённым условиям конкретной МФО. Обязательно указывать реального кредитора и предупреждение «Оценивайте свои финансовые возможности и риски».

Слова и обещания «вам одобрен», «предодобрен», «гарантируем», «одобряем всем», «100% одобрение» блокируются в массовых шаблонах. Персональное сообщение о предварительном одобрении разрешается только после интеграции с конкретной МФО, если партнёр прислал индивидуальный подтверждённый статус, связанный с этим пользователем и не истёкший.

### 7.3 Импорт списка контактов

CSV импортируется через preview:
- VK user ID;
- дата согласия на рекламные сообщения;
- источник согласия;
- версия текста согласия;
- ссылка/ID доказательства согласия;
- дата добавления в список.

Строки без обязательных сведений о предварительном рекламном согласии отклоняются и не попадают в отправочную очередь. Импортированный список сам по себе не подтверждает разрешение VK: перед каждой отправкой backend вызывает `messages.isMessagesFromGroupAllowed`. Если VK permission отсутствует, запись получает `skipped_no_vk_permission`.

Дубликаты объединяются по VK ID. Контакты из suppression list никогда не возвращаются в кампанию без нового подтверждённого согласия.

### 7.4 Автопривлечение новой аудитории

Под «автопоиском» в первой версии понимается Audience Builder для официального рекламного кабинета VK:
- подготовка рекламного креатива и destination link;
- генерация кампаний/UTM/ref параметров;
- настройка не-чувствительных параметров таргетинга, разрешённых актуальными правилами VK;
- входящие пользователи начинают диалог сами;
- статистика источника связывается с click/conversion.

Не реализовывать сбор персональных VK ID из поиска, групп, участников или открытых профилей и не отправлять им холодные сообщения. Прямое создание/управление рекламными кампаниями через VK Ads API — отдельная интеграция после проверки доступности API и получения advertiser token/прав. MVP не должен зависеть от API, если кабинет позволяет запустить кампанию вручную по сгенерированным материалам и ссылкам.

## 8. VK community bot integration

Backend:
- `POST /vk/callback` — VK Callback API webhook;
- проверка callback secret и group_id;
- `confirmation` event возвращает строку подтверждения из env;
- поддерживаемый MVP event: `message_new`;
- ответы отправляются только через group access token;
- сообщения из неизвестных групп/невалидных callback payload отвергаются;
- API запросы выполняются через aiohttp с таймаутом, обработкой VK error codes и ограничением частоты.

Конфигурация окружения:
- `VK_ENABLED=false`;
- `VK_GROUP_ID=`;
- `VK_GROUP_TOKEN=`;
- `VK_CALLBACK_SECRET=`;
- `VK_CONFIRMATION=`;
- `VK_API_VERSION=` (зафиксированное проверенное значение);
- `VK_COMMUNITY_URL=`;
- `VK_PUBLIC_BASE_URL=`;
- `VK_PRIVACY_URL=`;
- `VK_ADVERTISER_NAME=`;
- `VK_ADVERTISER_INN=` при необходимости;
- ключи рекламной маркировки/ERID не фиксировать как общие placeholders, хранить в настройках кампании с контрольным доступом.

VK integration выключена по умолчанию. Отсутствующие переменные не должны ломать запуск Telegram-бота.

## 9. Админ-панель

Добавить секцию «VK Marketing» в существующую web admin (не отдельный сайт).

Внутренние вкладки:

1. **Обзор**
   - входящие диалоги;
   - контакты с согласием;
   - рекламные согласия;
   - доступные/недоступные VK recipients;
   - отправки, ошибки, отписки;
   - клики по каждому из 5 слотов;
   - разбивка по campaign/source;
   - подтверждённые конверсии, только если пришли реальные данные.

2. **Пять ссылок**
   - 4 карточки МФО;
   - 1 карточка CPA-витрины;
   - название, описание, URL, tracking parameter, активность;
   - проверка HTTPS и preview;
   - кнопка «Проверить ссылку» не должна выдавать ложный статус одобрения.

3. **Контакты**
   - VK ID, дата первого диалога, наличие телефона (сам телефон замаскирован), статусы согласий, источник/кампания;
   - поиск, фильтры, импорт CSV;
   - экспорт только обезличенной аналитики;
   - просмотр доказательства согласия по правам администратора;
   - удалить/анонимизировать по валидному запросу.

4. **Кампании**
   - создание, предпросмотр, расписание;
   - выбор только проверяемых opt-in сегментов;
   - recipient estimate и причины исключений;
   - pause/resume/cancel;
   - прогресс, отправлено, пропущено, ошибки;
   - повторная попытка только для безопасно retryable ошибок и с idempotency key.

5. **Аудит и согласия**
   - кто создал/изменил кампанию;
   - кто импортировал контакты;
   - версия и timestamp каждого consent;
   - кто отозвал/удалил;
   - suppression list.

6. **Привлечение**
   - генератор VK Ads campaign brief;
   - варианты текста;
   - destination link/UTM/ref;
   - безопасные сегменты;
   - результаты по каналам.

## 10. Очередь отправки

Использовать durable DB queue, а не один asyncio task в памяти:
- кампания создаётся как draft;
- при подтверждении создаются recipient jobs;
- dispatcher выбирает только eligible recipients;
- перед фактической отправкой повторно проверяет рекламное согласие, отсутствие отзыва и VK permission;
- каждое событие имеет уникальный idempotency key;
- статусы: pending, sending, sent, skipped_no_marketing_consent, skipped_no_vk_permission, skipped_suppressed, failed_retryable, failed_permanent;
- ограничение скорости configurable и согласовано с актуальными лимитами VK API;
- retries с exponential backoff только для временных ошибок;
- после рестарта зависшие `sending` возвращаются в pending, если отправка точно не была подтверждена;
- если результат вызова VK неизвестен, не делать слепую повторную отправку;
- администратор может остановить кампанию;
- ошибки по одному пользователю не останавливают всю кампанию.

## 11. Данные и миграция

Новая additive Alembic migration после текущего head `0009_admin_audit_events`. Не изменять и не удалять старые Telegram-таблицы.

Рекомендуемые модели:

### VkContact
- id (internal PK);
- vk_user_id (unique);
- first_name/last_name (nullable, минимально необходимые);
- phone_encrypted;
- phone_hash (index);
- personal_data_consent_at;
- marketing_consent_at (nullable);
- marketing_consent_version;
- marketing_consent_source;
- withdrawn_at;
- source_campaign;
- first_seen_at, last_seen_at, created_at, updated_at.

### VkConsentEvent
Append-only audit:
- id;
- vk_contact_id;
- consent_type (personal_data, marketing, partner_data_transfer);
- action (granted, withdrawn);
- text_version;
- source;
- proof_reference;
- occurred_at;
- metadata_json without phone/secrets.

### VkOfferSlot
- id;
- slot_number (unique, 1..5);
- kind (mfo_offer/storefront);
- advertiser_name;
- title;
- description;
- target_url;
- tracking_param (nullable);
- enabled;
- updated_by;
- updated_at.

### VkClick
- id;
- opaque_token_hash (unique);
- vk_contact_id;
- slot_number;
- campaign_id nullable;
- source/ref;
- created_at;
- destination_domain;
- outcome (redirected/blocked/invalid).

### VkCampaign
- id;
- admin_id;
- name;
- text;
- CTA label;
- status;
- targeting_json (non-sensitive and no user-level lists);
- audience_type;
- advertiser display name;
- warning text;
- ERID/marking fields where applicable;
- scheduled_at, started_at, completed_at;
- recipient_count, sent_count, skipped_count, failed_count;
- created_at, updated_at.

### VkCampaignRecipient
- id;
- campaign_id;
- vk_contact_id;
- status;
- attempt_count;
- idempotency_key unique;
- last_error_code;
- next_attempt_at;
- sent_at;
- unique(campaign_id, vk_contact_id).

All migrations additive. Phone is encrypted with existing Fernet key and hashed with existing configured salt. Phone must be redacted from logs and admin overview.

## 12. API boundaries

Add VK-specific modules rather than growing `bot/tma_api.py` further:
- `bot/vk/client.py`: typed VK API client and error mapping;
- `bot/vk/callback.py`: webhook validation and event dispatch;
- `bot/vk/flow.py`: start/consent/phone/menu state machine;
- `bot/vk/outreach.py`: campaign eligibility, list import, dispatcher;
- `bot/vk/tracking.py`: token creation and redirect resolution;
- `bot/vk/admin_api.py`: admin JSON endpoints;
- `bot/vk/copy_policy.py`: campaign content validation.

All VK admin endpoints must validate existing admin session and `cfg.admins` server-side. Frontend visibility is not authorization.

Suggested route namespace:
- `POST /vk/callback`
- `GET /vk/go/{token}`
- `GET /api/v1/admin/vk/overview`
- `GET/PUT /api/v1/admin/vk/slots`
- `GET/POST /api/v1/admin/vk/campaigns`
- `POST /api/v1/admin/vk/campaigns/preview`
- `POST /api/v1/admin/vk/campaigns/{id}/send`
- `POST /api/v1/admin/vk/campaigns/{id}/pause`
- `POST /api/v1/admin/vk/campaigns/{id}/resume`
- `POST /api/v1/admin/vk/contacts/import/preview`
- `POST /api/v1/admin/vk/contacts/import/commit`
- `GET /api/v1/admin/vk/contacts`
- `GET /api/v1/admin/vk/campaigns/{id}`

## 13. Operational setup required from owner

The developer can prepare code and configuration, but a real VK channel cannot be activated without:
- VK community/group;
- enabled community messages;
- group access token with the minimum required messages permissions;
- configured Callback API endpoint, secret and confirmation string;
- public HTTPS Bonvera URL;
- four approved MFO partner links (or explicit disabled slots);
- the owner's fifth CPA storefront URL;
- legal business/advertiser details and approved advertising copy;
- privacy policy URL and Russian production database location;
- if direct VK Ads API is enabled later: advertiser account and API access token.

Never ask the owner to paste a private token into chat or commit it. Set it in server secret configuration.

## 14. Acceptance criteria

### Bot
- VK Callback confirmation works.
- Invalid secret/group ID is rejected.
- Telegram service continues normally with VK disabled.
- New VK user gets welcome and explicit privacy flow.
- No phone accepted before personal-data consent.
- Phone is encrypted, normalized and redacted in logs.
- Declining marketing consent does not block offers.
- Bot shows four MFO buttons + one CPA storefront button only when corresponding slot is active/configured.
- Each click records correct slot/contact/campaign and redirects safely.
- No phone/VK ID is appended to CPA URL.

### Campaigns
- Campaign preview reports eligible, excluded and reason counts.
- Sending only to opted-in contacts with VK message permission.
- Missing or revoked consent always excludes recipient.
- Imported list without consent evidence cannot be sent.
- Duplicate import does not create duplicate recipients.
- Campaign persists across restart and does not blindly double-send.
- Pause/cancel works.
- No personal-profile search/scraping or cold-DM code exists.

### Advertising copy
- Static generic template cannot claim user-specific approval.
- Unverified «предодобрен/одобрен/гарантирован/100%» language is blocked.
- Actual verified preapproval mode is unavailable until a partner integration supplies per-user result.
- Offer maximums and lender identity come from verified admin-entered data.
- Required loan warning and advertiser/marking fields are validated.

### Admin
- Slots 1–5 editable and validated.
- Fifth link remains empty until owner enters it.
- Contact phone is masked by default.
- Consent history and suppression are visible.
- Campaign analytics separate sends/clicks from actual conversions.

### Release
- Backend and frontend tests pass.
- Migration tested on test DB.
- VK callback is tested with VK test community.
- Real external partner links are checked by owner before activation.
- No production deployment or migrations without owner's separate instruction.

## 15. Regulatory and platform references to verify before release

This is an engineering implementation brief, not a legal opinion. Counsel/operator must validate the final campaign and data flow.

- Russian Advertising Law 38-FZ, Article 18 (prior consent for advertising by communication networks): https://www.consultant.ru/document/cons_doc_LAW_58968/f892dec1383709792452f18d36e7043306e2be0a/
- Russian Advertising Law 38-FZ, Article 28 (financial-services ads and consumer-loan warning): https://www.consultant.ru/document/cons_doc_LAW_58968/0021818db8b93ae5fbd38076074a7182e157186c/
- Personal Data Law 152-FZ, Article 9 (separate, specific and provable consent): https://www.consultant.ru/document/cons_doc_LAW_61801/6c94959bc017ac80140621762d2ac59f6006b08c/
- Personal Data Law 152-FZ, Article 18 (Russian citizen data localization requirements): https://www.consultant.ru/document/cons_doc_LAW_61801/cbf4e15b7c330f9372e876cdf2bc928bad7950ef/
- Bank of Russia/FAS position on separate, non-automatic advertising consent: https://cbr.ru/press/event/?id=12192
- VK community messaging permission method in VKCOM SDK/schema: https://github.com/VKCOM/vk-php-sdk/blob/master/src/VK/Actions/Messages.php and https://github.com/VKCOM/api-schema-typescript/blob/master/src/methods/messages.ts
- VK Bridge phone API exists, but this MVP uses explicit chat input unless a later UX task chooses VK Mini App phone request: https://github.com/VKCOM/vk-mini-apps-api/blob/master/src/index.ts

