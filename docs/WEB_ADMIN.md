# BONVERA web admin

The admin workspace is served by the existing web application and backend; it does not require opening the Telegram Mini App.

- Browser entry: `/admin` redirects to `/app/admin/login`.
- The Telegram bot `/admin` command includes a shortcut to the browser panel when `WEBAPP_URL` is configured.
- Login uses the official Telegram Login Widget. The backend verifies its HMAC signature, rejects payloads older than 10 minutes, and only issues a session to IDs in `ADMINS`. Admin API routes check the allowlist again.
- Sessions use the existing `tma_sessions` table and normal server-side bearer-session validation. No database migration is required.

## One-time Telegram setup

In `@BotFather`, run `/setdomain`, select the BONVERA bot, and set the exact public hostname used by `WEBAPP_URL` (hostname only, without `https://` or a path). The site must be served over HTTPS. This is required by Telegram's Login Widget and cannot be configured by the application itself.

## Current sections

- Overview and operational counters
- User directory with search
- Applications and payout queues
- Offer list with guarded enable/disable
- Broadcast campaign history
- Finance totals with an explicit distinction between network postbacks and cash actually received

Offer activation requires a partner URL. Bookmaker offers additionally require `network_status=approved` and a recorded approval note. Payouts can be moved to processing and marked paid only after a separate browser confirmation; marking paid does not transfer money. The actual bank transfer remains manual.

Production deployment and database migrations are intentionally not performed by this implementation task.
