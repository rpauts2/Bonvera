# VK MFO Outreach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a VK community bot, a five-link MFO/CPA lead funnel, consent-safe contact management, durable opted-in campaign broadcasts, tracking, and a VK marketing area in Bonvera admin.

**Architecture:** Extend the existing aiohttp + PostgreSQL/Alembic backend; do not create a second service or database. Keep VK contacts, consents, campaigns and clicks separate from Telegram users while reusing encryption, hashing, admin session checks, and the existing React admin shell.

**Tech Stack:** Python 3.11, aiohttp, SQLAlchemy async, Alembic, APScheduler, React 19, TypeScript, Vite, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-11-22-vk-mfo-outreach-design.md`

## Global Constraints

- Work only on `feat/vk-mfo-outreach`, based on `feat/bonvera-mini-app-v2`; never modify `main`.
- `VK_ENABLED=false` by default; Telegram must continue working when VK credentials are absent.
- Use the existing PostgreSQL database and additive Alembic migrations only.
- No cold DM, profile scraping, member scraping, ID enumeration, permission bypass, or sending to imported contacts without evidence of prior ad consent.
- Before each advertising message, check both recorded advertising opt-in and VK `messages.isMessagesFromGroupAllowed`.
- No static or unverified claims of approval, preapproval, guaranteed approval, or "approves everyone".
- Offer slots 1–4 and CPA storefront slot 5 are editable; do not invent or hardcode partner URLs. Slot 5 stays disabled until the owner adds their CPA URL.
- Store phones encrypted with existing helpers and redact them from logs, events, errors, and URLs.
- Do not auto-forward phone numbers to any MFO or CPA partner.
- Never put secrets in source control. Never deploy, migrate production, or send a live campaign without separate owner instruction.
- Use TDD: add a failing test, run it and verify the expected failure, implement, rerun targeted and full tests.

## Review Focus

- Invalid VK Callback secret/group ID must not reach the flow handler.
- Duplicate callback deliveries must not create duplicate contacts, consent events, clicks, or outbound campaign sends.
- A contact who granted personal-data consent but not advertising consent may receive the requested bot flow but must never enter a marketing campaign.
- A contact with advertising opt-in but no current VK community-message permission must be skipped.
- A contact who revoked consent after campaign preview must be excluded at send time.
- Empty/invalid fifth CPA URL must not render a broken storefront button.
- Redirect targets must be restricted to validated HTTPS URLs to prevent open redirects.
- An unknown send outcome must not trigger a blind duplicate send.

---

## File Map

**Create**
- `bot/vk/__init__.py` — VK package.
- `bot/vk/client.py` — VK API client, error mapping, permission check and message send.
- `bot/vk/callback.py` — Callback API validation and event dispatch.
- `bot/vk/flow.py` — start, consent, phone and five-link conversation state machine.
- `bot/vk/tracking.py` — opaque click token and redirect resolution.
- `bot/vk/copy_policy.py` — ad copy checks and required disclosure validation.
- `bot/vk/outreach.py` — import preview, audience eligibility, durable queue dispatcher.
- `bot/vk/admin_api.py` — admin endpoints for contacts, slots and campaigns.
- `webapp/src/pages/AdminVk.tsx` — VK Marketing workspace.
- `tests/test_vk_config.py`
- `tests/test_vk_client.py`
- `tests/test_vk_callback.py`
- `tests/test_vk_flow.py`
- `tests/test_vk_tracking.py`
- `tests/test_vk_outreach.py`
- `tests/test_vk_admin_api.py`
- `tests/test_vk_copy_policy.py`
- `webapp/tests/vk-marketing.test.mjs`
- `alembic/versions/0010_vk_mfo_outreach.py`

**Modify**
- `bot/config.py` — VK env settings and fail-safe validation.
- `bot/db.py` — VK ORM models and indexes.
- `bot/web.py` — mount webhook and redirect handlers in the existing aiohttp app.
- `bot/__main__.py` — start/stop VK dispatcher only when enabled.
- `bot/tma_api.py` — mount VK admin APIs or delegate to `bot/vk/admin_api.py`.
- `webapp/src/pages/Admin.tsx` — add VK Marketing navigation/entry.
- `.env.example` — document VK placeholders only.
- `README.md` / `docs/VK_OUTREACH.md` — setup and operator runbook.
- `tests/conftest.py` — shared VK fixtures if needed.

## Task 1: Database and consent foundation

**Files:**
- Modify: `bot/db.py`
- Create: `alembic/versions/0010_vk_mfo_outreach.py`
- Test: `tests/test_vk_config.py` (migration/schema section) or new `tests/test_vk_models.py`

**Interfaces:**
- `VkContact`: VK identity, minimal profile fields, encrypted phone, phone hash, bot flow state, current consent state, suppression state and timestamps.
- `VkConsentEvent`: append-only personal-data / marketing consent grant and withdrawal with version, evidence source and time.
- `VkOfferSlot`: unique `slot_number` 1–5, kind, advertiser, label, HTTPS target URL, optional CPA parameter, enabled flag, audit fields.
- `VkClick`: unique opaque token hash, contact, slot, campaign, source, destination host, time.
- `VkCampaign`: copy, advertiser disclosure, warning, schedule, audience type, status and counters.
- `VkCampaignRecipient`: durable per-contact job, status, attempt count, idempotency key, retry time and last error.
- Migration head becomes `0010_vk_mfo_outreach`; no existing Telegram rows/columns are removed.

- [ ] **Step 1: Write failing model and migration tests**
  - `test_vk_tables_are_registered_in_base_metadata`
  - `test_vk_offer_slot_restricts_slot_number_to_one_through_five`
  - `test_vk_campaign_recipient_is_unique_per_campaign_and_contact`
  - `test_vk_consent_events_are_append_only_records`
  - `test_alembic_head_is_0010_vk_mfo_outreach`

- [ ] **Step 2: Run the targeted tests and confirm expected failures**

Run: `pytest tests/test_vk_models.py -q` and `pytest tests/test_catalog.py -q`.

Expected: failures only because the VK schema/migration is absent.

- [ ] **Step 3: Add ORM models and additive Alembic migration**

Create the six models above with proper foreign keys, unique constraints, indexes on VK ID, phone hash, campaign/status, and timestamps. Reuse `phone_encrypt` / `phash` at the service layer, not in the ORM.

- [ ] **Step 4: Run targeted tests and migration upgrade/downgrade against an isolated test database**

Run: `pytest tests/test_vk_models.py -q`; run Alembic upgrade and downgrade on an ephemeral database.

Expected: all schema tests pass; existing tables remain unchanged.

- [ ] **Step 5: Commit**

`feat(vk): add contacts consents offers and campaign schema`

## Task 2: VK configuration and API client

**Files:**
- Modify: `bot/config.py`, `.env.example`
- Create: `bot/vk/__init__.py`, `bot/vk/client.py`
- Test: `tests/test_vk_config.py`, `tests/test_vk_client.py`

**Interfaces:**
- `VKClient(method: str, params: dict) -> dict`
- `VKClient.is_messages_allowed(vk_user_id: int) -> bool`
- `VKClient.send_message(vk_user_id: int, text: str, keyboard: dict, random_id: int) -> dict`
- Required secrets: group token and Callback secret; group ID, confirmation string, public base URL and API version are non-secret configuration.

- [ ] **Step 1: Write failing tests**
  - `test_vk_disabled_by_default`
  - `test_missing_vk_credentials_do_not_break_telegram_config`
  - `test_vk_client_uses_group_token_and_configured_api_version`
  - `test_permission_check_returns_false_for_vk_denial`
  - `test_vk_api_errors_are_mapped_without_logging_tokens`
  - `test_send_uses_stable_random_id`

- [ ] **Step 2: Run tests and verify they fail for missing implementation**

Run: `pytest tests/test_vk_config.py tests/test_vk_client.py -q`.

- [ ] **Step 3: Implement typed VK client**

Use aiohttp with explicit connect/read timeout, form-encoded method requests, configured API version, safe structured errors, no logging of access tokens or phone values. Honor VK API retryable vs permanent errors; never invent rate limits.

- [ ] **Step 4: Run targeted tests**

Run: `pytest tests/test_vk_config.py tests/test_vk_client.py -q`.

- [ ] **Step 5: Commit**

`feat(vk): add VK community API client and config`

## Task 3: Callback API and bot flow

**Files:**
- Create: `bot/vk/callback.py`, `bot/vk/flow.py`
- Modify: `bot/web.py`, `bot/__main__.py`
- Test: `tests/test_vk_callback.py`, `tests/test_vk_flow.py`

**Interfaces:**
- `handle_vk_callback(request) -> web.Response`
- `handle_vk_message(event: dict, vk_client: VKClient) -> None`
- `handle_start(vk_user_id: int, campaign_ref: str | None) -> None`
- `handle_phone(vk_user_id: int, text: str) -> None`
- `handle_consent(vk_user_id: int, consent_type: str, accepted: bool) -> None`

- [ ] **Step 1: Write failing webhook tests**
  - `test_callback_confirmation_returns_configured_confirmation`
  - `test_callback_rejects_wrong_secret`
  - `test_callback_rejects_wrong_group_id`
  - `test_duplicate_message_event_is_idempotent`

- [ ] **Step 2: Run tests and confirm missing endpoint/validation failures**

Run: `pytest tests/test_vk_callback.py -q`.

- [ ] **Step 3: Implement callback handler**

Validate event type, group ID, secret and JSON shape. Support confirmation and `message_new` for MVP. Add webhook route without changing Telegram routes.

- [ ] **Step 4: Write failing conversation tests**
  - `test_start_creates_vk_contact_and_sends_welcome`
  - `test_phone_is_rejected_before_personal_data_consent`
  - `test_phone_is_encrypted_and_normalized_after_consent`
  - `test_declining_marketing_consent_still_reveals_offer_menu`
  - `test_stop_withdraws_marketing_consent_and_suppresses_contact`
  - `test_menu_has_four_mfo_links_and_one_storefront_link`

- [ ] **Step 5: Implement persistent flow state**

Use VK contact row state; do not keep user progress only in process memory. Reuse existing phone encryption/hash helpers. Do not put phone in outbound notifications or URL.

- [ ] **Step 6: Run targeted and existing Telegram tests**

Run: `pytest tests/test_vk_callback.py tests/test_vk_flow.py tests/test_bot_launch.py tests/test_tma_api.py -q`.

- [ ] **Step 7: Commit**

`feat(vk): add community webhook and lead conversation`

## Task 4: Five offer slots and click redirects

**Files:**
- Create: `bot/vk/tracking.py`
- Modify: `bot/web.py`, `bot/vk/flow.py`
- Test: `tests/test_vk_tracking.py`

**Interfaces:**
- `validate_external_target(url: str) -> str`
- `create_click(contact_id: int, slot_number: int, campaign_id: int | None) -> str`
- `resolve_click(token: str) -> RedirectResult`
- `render_offer_keyboard(slots: list[VkOfferSlot], contact_id: int) -> dict`

- [ ] **Step 1: Write failing tests**
  - `test_slots_are_exactly_four_mfo_slots_and_one_storefront_slot`
  - `test_unconfigured_storefront_is_not_rendered`
  - `test_invalid_or_non_https_target_is_rejected`
  - `test_redirect_records_slot_contact_and_campaign`
  - `test_click_token_is_opaque_and_phone_never_enters_url`
  - `test_configured_tracking_param_gets_click_token_once`
  - `test_redirect_rejects_unknown_or_expired_token`

- [ ] **Step 2: Run targeted tests and verify expected failures**

Run: `pytest tests/test_vk_tracking.py -q`.

- [ ] **Step 3: Implement slot management rules and redirect handler**

Never accept an arbitrary redirect URL from the request. Resolve only a saved active slot. Maintain a fixed allowlist of schemes (HTTPS only) and reject unsafe userinfo, local/private IP destinations and malformed URLs. A tracking parameter is appended only if the slot owner configured it.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_vk_tracking.py tests/test_vk_flow.py -q`.

- [ ] **Step 5: Commit**

`feat(vk): add editable five-slot MFO funnel and click tracking`

## Task 5: Campaign copy policy and opt-in contact import

**Files:**
- Create: `bot/vk/copy_policy.py`, `bot/vk/outreach.py`
- Test: `tests/test_vk_copy_policy.py`, `tests/test_vk_outreach.py`

**Interfaces:**
- `validate_campaign_copy(text: str, advertiser: str, warning: str, approval_evidence: dict | None) -> CopyValidation`
- `preview_contact_import(csv_text: str) -> ImportPreview`
- `commit_contact_import(preview_id: str, admin_id: int) -> ImportResult`
- `is_recipient_eligible(contact: VkContact, vk_permission: bool, now: datetime) -> Eligibility`

- [ ] **Step 1: Write failing copy-policy tests**
  - `test_requires_advertiser_identity`
  - `test_requires_financial_services_warning`
  - `test_blocks_unverified_preapproval_claims`
  - `test_allows_per_user_preapproval_only_with_valid_partner_evidence`
  - `test_rejects_unsubstantiated_max_amount`

- [ ] **Step 2: Run copy tests and verify expected failures**

Run: `pytest tests/test_vk_copy_policy.py -q`.

- [ ] **Step 3: Implement content validation**

Validate required disclosures, advertiser and source-backed offer parameters. Keep the rule explicit: generic campaign content cannot claim a specific user's loan is approved unless a specific partner result proves it.

- [ ] **Step 4: Write failing contact import/eligibility tests**
  - `test_import_rejects_rows_without_consent_date_source_version_and_evidence`
  - `test_import_deduplicates_vk_ids`
  - `test_import_preview_does_not_write_contacts`
  - `test_marketing_opt_in_is_required_for_campaign`
  - `test_vk_permission_is_required_for_campaign`
  - `test_revoked_consent_is_excluded_even_after_preview`
  - `test_suppressed_contact_is_never_eligible`

- [ ] **Step 5: Implement strict CSV preview/import and eligibility checks**

Allow import of contacts only with row-level proof metadata. The upload itself never means consent. Re-check both consent and VK permission immediately before send.

- [ ] **Step 6: Run targeted tests**

Run: `pytest tests/test_vk_copy_policy.py tests/test_vk_outreach.py -q`.

- [ ] **Step 7: Commit**

`feat(vk): validate MFO ad copy and import opted-in contacts`

## Task 6: Durable campaign dispatcher and attribution

**Files:**
- Modify: `bot/vk/outreach.py`, `bot/vk/client.py`, `bot/__main__.py`
- Create: `tests/test_vk_campaign_dispatch.py`

**Interfaces:**
- `create_campaign_draft(admin_id: int, payload: CampaignInput) -> VkCampaign`
- `preview_campaign(campaign_id: int) -> CampaignPreview`
- `start_campaign(campaign_id: int, admin_id: int) -> None`
- `pause_campaign(campaign_id: int, admin_id: int) -> None`
- `dispatch_campaign_batch(batch_size: int = 20) -> DispatchResult`

- [ ] **Step 1: Write failing dispatcher tests**
  - `test_campaign_preview_counts_eligible_and_excluded_with_reasons`
  - `test_send_rechecks_consent_and_vk_permission`
  - `test_duplicate_job_does_not_send_twice`
  - `test_retryable_error_uses_backoff`
  - `test_unknown_send_outcome_is_not_blindly_retried`
  - `test_paused_campaign_stops_dispatching`
  - `test_pending_campaign_resumes_after_worker_restart`

- [ ] **Step 2: Run tests and verify expected failures**

Run: `pytest tests/test_vk_campaign_dispatch.py -q`.

- [ ] **Step 3: Implement persistent dispatcher**

Use database jobs and idempotency keys. Before each send, recheck consent, suppression and VK permission. Use configurable conservative throughput and VK API responses rather than hardcoded undocumented limits. Pause on authentication/configuration failures; do not stop unrelated users' flow.

- [ ] **Step 4: Run campaign tests and existing bot tests**

Run: `pytest tests/test_vk_campaign_dispatch.py tests/test_broadcasts.py -q`.

- [ ] **Step 5: Commit**

`feat(vk): add durable opted-in campaign dispatcher`

## Task 7: VK admin API

**Files:**
- Create: `bot/vk/admin_api.py`, `tests/test_vk_admin_api.py`
- Modify: `bot/tma_api.py`, `bot/web.py`

**Interfaces:**
- `register_vk_admin_routes(app: web.Application) -> None`
- Endpoints as specified in the design doc: overview, slots, campaigns, import preview/commit, contacts, campaign pause/resume/details.

- [ ] **Step 1: Write failing endpoint tests**
  - `test_vk_admin_endpoints_reject_non_admin`
  - `test_vk_slots_update_requires_valid_https_urls`
  - `test_storefront_slot_5_is_independently_configurable`
  - `test_campaign_preview_is_read_only`
  - `test_campaign_send_requires_explicit_admin_confirmation`
  - `test_phone_is_masked_in_contact_api`
  - `test_import_commit_requires_valid_preview_token`

- [ ] **Step 2: Run tests and verify missing route/authorization failures**

Run: `pytest tests/test_vk_admin_api.py -q`.

- [ ] **Step 3: Implement admin routes**

Reuse existing session middleware and server-side `cfg.admins` check. Never trust UI-only restrictions. Audit all writes with admin ID.

- [ ] **Step 4: Run targeted and TMA hardening tests**

Run: `pytest tests/test_vk_admin_api.py tests/test_tma_hardening.py tests/test_tma_headers.py -q`.

- [ ] **Step 5: Commit**

`feat(vk): add authenticated VK marketing admin APIs`

## Task 8: Admin UI

**Files:**
- Create: `webapp/src/pages/AdminVk.tsx`, `webapp/tests/vk-marketing.test.mjs`
- Modify: `webapp/src/pages/Admin.tsx`, `webapp/src/components/Icon.tsx` only if a supported icon is needed.

**Interfaces:**
- `AdminVk` renders Overview, Five Links, Contacts, Campaigns, Audience Builder and Consent Audit.
- All data/actions use the existing `api` client.
- Keep the existing admin shell, typography and dark navy/cyan/purple visual language.

- [ ] **Step 1: Write failing UI/API contract tests**
  - `test_vk_admin_page_loads_overview`
  - `test_five_slots_show_four_mfo_and_one_storefront`
  - `test_empty_slot_five_is_marked_unconfigured`
  - `test_campaign_preview_shows_eligible_and_excluded_counts`
  - `test_send_requires_preview_and_confirmation`
  - `test_contact_phone_is_masked_by_default`

- [ ] **Step 2: Run frontend tests and verify expected failures**

Run: `cd webapp && npm test -- --test-name-pattern=vk-marketing`.

- [ ] **Step 3: Implement page and navigation**

Include campaign composer, message preview, safe copy validation errors, import CSV preview, slot editor, contacts/consents table, analytics and pause/cancel controls. No inert buttons.

- [ ] **Step 4: Run frontend suite and production build**

Run: `cd webapp && npm test && npm run build`.

- [ ] **Step 5: Commit**

`feat(admin): add VK marketing workspace`

## Task 9: Audience acquisition and documentation

**Files:**
- Create: `docs/VK_OUTREACH.md`, optional helper `bot/vk/ads.py` only after VK Ads API is verified.
- Modify: `README.md`, `.env.example`
- Test: `tests/test_vk_attribution.py`

- [ ] **Step 1: Write failing attribution tests**
  - `test_campaign_ref_is_persisted_on_start`
  - `test_untrusted_campaign_ref_is_not_used_as_redirect_target`
  - `test_unknown_campaign_ref_falls_back_to_organic_source`

- [ ] **Step 2: Verify source/UTM handling and campaign attribution**

- [ ] **Step 3: Implement Audience Builder**

Generate VK Ads campaign brief, safe campaign copy and tracked destination links. Any direct VK Ads API operations require a verified current API contract and owner-provided advertiser token; otherwise the first release exports the brief and tracking URL for setup in the VK Ads cabinet.

- [ ] **Step 4: Document VK community setup, Callback API, token permissions, privacy flow, CPA slot setup, legal/advertising review, campaign import and runbook**

The fifth CPA storefront URL is entered by the owner in admin and remains blank until configured.

- [ ] **Step 5: Run backend and frontend tests/build**

Run: `pytest -q`; `cd webapp && npm test && npm run build`; `git diff --check`.

- [ ] **Step 6: Commit**

`docs(vk): add VK acquisition setup and operator runbook`

## Task 10: QA and activation gate

- [ ] Test Callback confirmation against a VK test community.
- [ ] Test real message-new event from a human-initiated conversation.
- [ ] Test phone consent, phone encryption and phone redaction.
- [ ] Test 4 MFO links + owner-entered fifth CPA URL.
- [ ] Test all click redirects and partner sub-ID behavior.
- [ ] Import a test list with valid consent evidence and one invalid row.
- [ ] Verify invalid row is rejected and contacts without current VK permission are skipped.
- [ ] Run campaign in dry-run first; no real sends before explicit confirmation.
- [ ] Verify opt-out prevents subsequent campaigns.
- [ ] Verify campaign pause/restart/idempotency.
- [ ] Test mobile VK client and desktop VK client.
- [ ] Verify data location/hosting and legal copy before production.
- [ ] Obtain owner approval before configuring real tokens or enabling external sends.
- [ ] Do not deploy or run production migration as part of this plan.
