from aiohttp import web
from datetime import datetime, timedelta
import hmac
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from bot.config import cfg
from bot.db import *
from bot.logic import parse_subid, confirm, notify, clawback_credit

OK = {"approved", "confirmed", "paid", "1", "accepted"}
NO = {"rejected", "declined", "2", "cancelled"}
WAIT = {"hold", "pending", "0"}

def make_web(bot):
    async def pb(req):
        q = req.query
        logging.info("postback hit: method=%s keys=%s", req.method,
                     ",".join(sorted(k for k in q.keys() if k != "secret")))
        if req.method == "POST":
            # CPA networks differ: some send JSON, some form-encoded, some put
            # everything in the query string of a POST. Accept all three; the
            # query string stays authoritative when a key appears in both.
            data = {}
            try:
                if "application/json" in req.headers.get("Content-Type", ""):
                    payload = await req.json()
                    if isinstance(payload, dict):
                        data = {str(k): str(v) for k, v in payload.items() if v is not None}
                else:
                    form = await req.post()
                    data = {str(k): str(v) for k, v in form.items()}
                    if not data:
                        body = await req.text()
                        if body and "=" in body:
                            from urllib.parse import parse_qsl
                            data = dict(parse_qsl(body, keep_blank_values=True))
            except Exception:
                data = {}
            if data:
                q = {**data, **dict(req.query)}
        supplied = q.get("secret", "")
        if not hmac.compare_digest(supplied, cfg.pb_secret):
            logging.warning("postback auth failed: got %d chars, expected %d", len(supplied), len(cfg.pb_secret))
            return web.json_response({"ok": False, "err": "auth"}, status=403)
        # ProCPA and many other networks put the deal reference in sub1.
        sid = q.get("subid") or q.get("sub1") or ""
        st = (q.get("status") or "").lower()
        try: payout = int(float(q.get("payout", 0) or 0))
        except (ValueError, TypeError): payout = 0
        if payout < 0: return web.json_response({"ok": False, "err": "payout"}, status=400)
        aid = parse_subid(sid)
        async with Session() as s:
            # Store only whitelisted operational fields; arbitrary network query params
            # may contain PII, credentials or tracking secrets.
            safe_q = {"subid": sid, "status": st, "payout": payout}
            # Network-side identifiers, useful for reconciliation with ProCPA.
            for key in ("click_id", "lead_id", "order_id", "offer_id", "currency"):
                val = q.get(key)
                if val:
                    safe_q[key] = str(val)[:64]
            s.add(PbLog(subid=sid, status=st, payout=payout, raw=str(safe_q))); await s.commit()
            if not aid: return web.json_response({"ok": False, "err": "subid"})
            a = (await s.execute(select(App).where(App.id == aid).with_for_update())).scalar_one_or_none()
            if not a: return web.json_response({"ok": False, "err": "app"})
            if st in OK and a.status in (CONFIRMED, PAID) and payout > 0 and a.payout <= 0:
                a.payout = payout
                s.add(DealEvent(app_id=a.id, actor_id=None, event="network_payout_received", from_status=a.status, to_status=a.status,
                                comment=f"Сеть прислала сумму выплаты {payout} ₽; начисление пользователю не изменялось"))
                await s.commit()
            elif st in OK and a.status == HOLD and (a.verification or {}).get("network_approved"):
                if payout > 0 and a.payout <= 0:
                    a.payout = payout
                    s.add(DealEvent(app_id=a.id, actor_id=None, event="network_payout_received", from_status=HOLD, to_status=HOLD,
                                    comment=f"Сеть прислала сумму выплаты {payout} ₽; дата окончания холда не изменена"))
                    await s.commit()
            elif st in OK and a.status not in (CONFIRMED, PAID, REJECTED, EXPIRED):
                # An approved lead enters the configured hold first. It becomes
                # withdrawable only after hold expires, unless admin force-confirms.
                if a.status != HOLD or not (a.verification or {}).get("network_approved"):
                    old = a.status
                    days = int((a.offer_snapshot or {}).get("hold_days", 30))
                    a.status = HOLD
                    a.payout = max(0, payout)
                    a.hold_until = datetime.utcnow() + timedelta(days=days)
                    ver = dict(a.verification or {}); ver["network_approved"] = True; a.verification = ver
                    a.hold_alerted_at = None
                    s.add(DealEvent(app_id=a.id, actor_id=None, event="network_approved_hold", from_status=old, to_status=HOLD,
                                    comment=f"Сеть подтвердила целевое действие; холд {days} дней до {a.hold_until:%Y-%m-%d}"))
                    await s.commit()
                    await notify(bot, a.user_id, f"✅ Партнёрская сеть подтвердила сделку #{a.id}.\n⏳ Вознаграждение {int((a.offer_snapshot or {}).get('reward',0))} ₽ в холде до {a.hold_until:%d.%m.%Y}. После окончания холда администратор проверит сделку и доказательства; деньги станут доступны после ручного подтверждения.")
            elif st in NO and a.status not in (REJECTED, EXPIRED):
                # Clawback: reverse prior cashback and referral reward if the network revokes a confirmed lead.
                u = await s.get(User, a.user_id)
                clawback_notices = []
                if a.status in (CONFIRMED, PAID) and a.cashback:
                    u, user_notices = await clawback_credit(
                        s, a.user_id, a.cashback, f"clawback:app:{a.id}", "clawback",
                        f"Отзыв подтверждённого лида сетью по сделке #{a.id}"
                    )
                    clawback_notices.extend(user_notices)
                    refrow = (await s.execute(select(RefAcc).where(RefAcc.app_id == a.id))).scalar_one_or_none()
                    if refrow and refrow.amount > 0:
                        _, ref_notices = await clawback_credit(
                            s, refrow.referrer_id, refrow.amount, f"clawback:ref:{a.id}", "referral_clawback",
                            f"Отзыв реферального начисления по сделке друга #{a.id}"
                        )
                        clawback_notices.extend(ref_notices)
                        refrow.amount = 0
                old_status = a.status
                a.status, a.reason = REJECTED, "Рекламодатель отклонил/отозвал лид"
                a.reviewed_at = datetime.utcnow()
                s.add(DealEvent(app_id=a.id, actor_id=None, event="network_rejected", from_status=old_status, to_status=REJECTED, comment=a.reason))
                await s.commit()
                for target_uid, notice in clawback_notices:
                    await notify(bot, target_uid, notice)
                if u and u.balance < 0:
                    for ad in cfg.admins:
                        await notify(bot, ad, f"⚠️ Clawback по сделке #{a.id}: баланс пользователя {u.id} стал отрицательным ({u.balance} ₽). Непроведённые выплаты отменены или заморожены для сверки.")
                await notify(bot, a.user_id, f"❌ Заявка #{a.id} отклонена или отозвана рекламодателем. Если награда уже начислялась, она сторнирована. Вопросы — 🆘 Поддержка.")
            elif st in WAIT and a.status == HOLD and (a.verification or {}).get("network_approved"):
                # ProCPA sends "pending" when a confirmed conversion is put back
                # on review. Drop the automatic approval so the lead is never paid
                # out on a revoked confirmation; the decision goes back to an admin.
                ver = dict(a.verification or {}); ver["network_approved"] = False; a.verification = ver
                s.add(DealEvent(app_id=a.id, actor_id=None, event="network_reapproval",
                                from_status=HOLD, to_status=HOLD,
                                comment="Сеть вернула конверсию на проверку (postback pending); автоодобрение снято"))
                await s.commit()
                for ad in cfg.admins:
                    await notify(bot, ad, f"⚠️ Сделка #{a.id}: сеть отозвала подтверждение. Автоодобрение снято, нужна ручная проверка.")
            elif st in WAIT and a.status not in (CONFIRMED, PAID, REJECTED, EXPIRED, HOLD):
                o = await s.get(Offer, a.offer_id)
                old_status = a.status
                days = int((a.offer_snapshot or {}).get("hold_days", o.hold))
                a.status, a.hold_until = HOLD, datetime.utcnow() + timedelta(days=days)
                ver = dict(a.verification or {}); ver.setdefault("network_approved", False); a.verification = ver
                s.add(DealEvent(app_id=a.id, actor_id=None, event="network_hold", from_status=old_status, to_status=HOLD, comment=f"Ожидается решение сети; контрольный срок {days} дней; postback status={st}"))
                await s.commit()
                await notify(bot, a.user_id, f"⏳ Сделка #{a.id} принята партнёром в обработку и находится в холде до {a.hold_until:%d.%m.%Y}.")
        # Echo the resolved deal so support can match a callback without reading logs.
        return web.json_response({"ok": True, "app": aid})
    app = web.Application(client_max_size=25 * 1024 * 1024)
    app.router.add_get("/postback", pb)
    # Same handler: ProCPA and most CPA networks default to POST callbacks.
    app.router.add_post("/postback", pb)
    async def health(req):
        from bot.monitoring import check_db, health_payload
        payload = health_payload()
        payload["db_live"] = await check_db()
        payload["ok"] = bool(payload["db_live"] and payload.get("ok", True))
        return web.json_response(payload, status=200 if payload["ok"] else 503)
    app.router.add_get("/health", health)
    from bot.tma_api import setup_tma
    setup_tma(app, bot)
    return app

def make_scheduler(bot):
    sch = AsyncIOScheduler()
    from bot.monitoring import HEALTH, watchdog
    from bot.retention import purge_expired_evidence
    HEALTH["started_at"] = datetime.utcnow().isoformat(timespec="seconds")
    async def expire():
        async with Session() as s:
            lim = datetime.utcnow() - timedelta(hours=cfg.booking_h)
            for a in (await s.execute(select(App).where(App.status == NEW, App.created < lim))).scalars().all():
                old = a.status; a.status = EXPIRED
                s.add(DealEvent(app_id=a.id, actor_id=None, event="expired", from_status=old, to_status=EXPIRED, comment="Истёк срок брони оформления"))
                await notify(bot, a.user_id, f"⌛️ Бронь сделки #{a.id} истекла. Можно взять предложение заново.")
            await s.commit()
    async def remind():
        async with Session() as s:
            lim = datetime.utcnow() - timedelta(hours=cfg.booking_h // 2)
            for a in (await s.execute(select(App).where(App.status == NEW, App.created < lim, App.reminder_sent == False))).scalars().all():
                await notify(bot, a.user_id, f"⏰ Сделка #{a.id}: осталось около {cfg.booking_h // 2} ч. Успей выполнить условие и загрузить подтверждение.")
                a.reminder_sent = True
            await s.commit()
    async def hold_check():
        async with Session() as s:
            for a in (await s.execute(select(App).where(App.status == HOLD, App.hold_until < datetime.utcnow(), App.hold_alerted_at.is_(None)))).scalars().all():
                approved = bool((a.verification or {}).get("network_approved"))
                note = "Срок холда истёк; сеть подтвердила ЦД, требуется ручная проверка доказательств администратором" if approved else "Контрольный срок истёк без подтверждения сети; требуется ручная сверка кабинета партнёра"
                a.hold_alerted_at = datetime.utcnow()
                s.add(DealEvent(app_id=a.id, actor_id=None, event="hold_elapsed", from_status=HOLD, to_status=HOLD, comment=note))
                for ad in cfg.admins:
                    await notify(bot, ad, f"⚠️ Сделка #{a.id}: {note}. Награда не начислена автоматически. Открой /admin → Холды → сделка.")
                await notify(bot, a.user_id, f"⏳ Срок холда по сделке #{a.id} завершился. Сделка передана на финальную ручную проверку; статус и сумма будут обновлены после решения администратора.")
            await s.commit()
    async def evidence_purge():
        """Чистка доказательств по политике хранения (ежедневно)."""
        try:
            await purge_expired_evidence(bot)
        except Exception:  # noqa: BLE001 — чистка не должна ронять планировщик
            logging.exception("не удалось выполнить чистку доказательств")
    async def stale_proofs_job():
        """Напоминание о незагруженных доказательствах: заявки 6-48 ч без прогресса.

        Одна попытка на заявку: флаг verification.proof_reminder_sent хранится в JSON
        и коммитится вместе с остальными изменениями прохода.
        """
        from bot.user import PROOF_REMINDER_TEXT, reminder_kb
        now = datetime.utcnow()
        found = sent = 0
        async with Session() as s:
            rows = (await s.execute(
                select(App).where(App.status.in_((NEW, PROOF)),
                                  App.created >= now - timedelta(hours=48),
                                  App.created <= now - timedelta(hours=6))
            )).scalars().all()
            for a in rows:
                ver = dict(a.verification or {})
                if ver.get("proof_reminder_sent"):
                    continue
                # Доказательство уже есть — файлом или отметкой о загрузке.
                if a.proof_files or ver.get("proof_submitted_at"):
                    continue
                found += 1
                hours = max(6, int((now - a.created).total_seconds() // 3600))
                try:
                    await notify(bot, a.user_id,
                                 PROOF_REMINDER_TEXT.format(app_id=a.id, hours=hours),
                                 reply_markup=reminder_kb())
                except Exception:  # noqa: BLE001 — одна заявка не должна ронять проход
                    logging.exception("не удалось напомнить о доказательствах по сделке #%s", a.id)
                    continue
                ver["proof_reminder_sent"] = now.isoformat(timespec="seconds")
                a.verification = ver
                sent += 1
            await s.commit()
        logging.info("stale_proofs: найдено %d, отправлено %d", found, sent)

    async def booking_expiring_job():
        """Напоминание за 6 ч до конца брони (booking_until = created + BOOKING_HOURS)."""
        from bot.user import BOOKING_REMINDER_TEXT, reminder_kb
        now = datetime.utcnow()
        found = sent = 0
        async with Session() as s:
            rows = (await s.execute(
                select(App).where(App.status == NEW,
                                  App.created > now - timedelta(hours=cfg.booking_h),
                                  App.created <= now + timedelta(hours=6 - cfg.booking_h))
            )).scalars().all()
            for a in rows:
                left = a.created + timedelta(hours=cfg.booking_h) - now
                if left <= timedelta(0) or left > timedelta(hours=6):
                    continue
                ver = dict(a.verification or {})
                if ver.get("booking_reminder_sent"):
                    continue
                found += 1
                hours = max(1, int(round(left.total_seconds() / 3600)))
                try:
                    await notify(bot, a.user_id,
                                 BOOKING_REMINDER_TEXT.format(app_id=a.id, hours=hours),
                                 reply_markup=reminder_kb())
                except Exception:  # noqa: BLE001
                    logging.exception("не удалось напомнить о брони по сделке #%s", a.id)
                    continue
                ver["booking_reminder_sent"] = now.isoformat(timespec="seconds")
                a.verification = ver
                sent += 1
            await s.commit()
        logging.info("booking_expiring: найдено %d, отправлено %d", found, sent)

    sch.add_job(expire, "interval", minutes=30)
    sch.add_job(remind, "interval", minutes=60)
    sch.add_job(hold_check, "interval", minutes=15)
    sch.add_job(evidence_purge, "interval", hours=24, id="evidence_purge", jitter=3600)
    async def network_silence():
        """Deals waiting for the network longer than a day mean the postback is broken."""
        from bot.db import App, PbLog, Session
        async with Session() as s:
            stuck = (await s.execute(
                select(App).where(App.status.in_([PROOF, HOLD]),
                                  App.created < datetime.utcnow() - timedelta(hours=24))
            )).scalars().all()
            if not stuck:
                return
            subids = [a.subid for a in stuck if a.subid]
            seen = set()
            if subids:
                seen = {row[0] for row in (await s.execute(select(PbLog.subid).where(PbLog.subid.in_(subids)))).all()}
            silent = [a for a in stuck if a.subid not in seen]
        if not silent:
            return
        text = (f"📡 <b>Сеть молчит</b>\n{len(silent)} заявок ждут подтверждения больше 24 ч "
                f"и ни по одной не было postback.\nПроверь настройку отправки в ProCPA.")
        for admin_id in cfg.admins:
            try:
                await bot.send_message(admin_id, text)
            except Exception:
                continue
    sch.add_job(network_silence, "interval", hours=6, id="network_silence")
    sch.add_job(stale_proofs_job, "interval", hours=2, id="stale_proofs", jitter=300)
    sch.add_job(booking_expiring_job, "interval", hours=1, id="booking_expiring", jitter=120)

    sch.add_job(watchdog, "interval", minutes=max(1, cfg.health_interval_min), id="watchdog", args=[bot])
    return sch
