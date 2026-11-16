# BONVERA web admin

The admin workspace is served by the existing web application and backend; it does not require opening the Telegram Mini App.

- Browser entry: `/admin` redirects to `/app/admin/login`.
- The Telegram bot `/admin` command includes a shortcut to the browser panel when `WEBAPP_URL` is configured.
- Login uses the official Telegram Login Widget. The backend verifies its HMAC signature, rejects payloads older than 10 minutes, and only issues a session to IDs in `ADMINS`. Admin API routes check the allowlist again.
- Sessions use the existing `tma_sessions` table and normal server-side bearer-session validation. Admin audit history is stored in `admin_audit_events`; apply Alembic migration `0009_admin_audit_events` before enabling the updated admin panel in a deployed environment.

## One-time Telegram setup

In `@BotFather`, run `/setdomain`, select the BONVERA bot, and set the exact public hostname used by `WEBAPP_URL` (hostname only, without `https://` or a path). The site must be served over HTTPS. This is required by Telegram's Login Widget and cannot be configured by the application itself.

## Current sections

- Overview and operational counters
- User directory with search
- Applications with authenticated evidence preview, guarded manual confirmation, hold and reasoned rejection; payout queues with processing, manual paid confirmation, and reasoned rejection/refund
- Offer list and editor with guarded enable/disable; material bookmaker changes automatically reset approval and disable the offer
- User ban/unban with self-lockout protection
- Durable administrator audit log for user, offer, application, payout and broadcast actions
- Broadcast composer with audience preview, explicit send confirmation, automatic Bonvera CTA button, background delivery and campaign history
- Finance totals with an explicit distinction between network postbacks and cash actually received

Offer activation requires a partner URL. Bookmaker offers additionally require `network_status=approved` and a recorded approval note. Payouts can be moved to processing and marked paid only after a separate browser confirmation; marking paid does not transfer money. The actual bank transfer remains manual. Web broadcasts currently support text messages up to Telegram’s 4096-character limit. Audience size is checked again at send time; if it changed after preview, sending is blocked until the admin previews again. Delivery progress is checkpointed in the campaign record; an interrupted worker is shown as interrupted rather than silently retried.

Production deployment and database migrations are intentionally not performed by this implementation task.
