from aiohttp import web
from datetime import datetime, timedelta
import hmac
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from bot.config import cfg
from bot.db import *
from bot.logic import parse_subid, confirm, notify, clawback_credit

OK = {"approved", "confirmed", "1", "accepted"}
NO = {"rejected", "declined", "2", "cancelled"}
WAIT = {"hold", "pending", "0"}

def make_web(bot):
    async def pb(req):
        q = req.query
        supplied = q.get("secret", "")
        if not hmac.compare_digest(supplied, cfg.pb_secret): return web.json_response({"ok": False, "err": "auth"}, status=403)
        sid, st = q.get("subid", ""), q.get("status", "").lower()
        try: payout = int(float(q.get("payout", 0) or 0))
        except (ValueError, TypeError): payout = 0
        if payout < 0: return web.json_response({"ok": False, "err": "payout"}, status=400)
        aid = parse_subid(sid)
        async with Session() as s:
            # Store only whitelisted operational fields; arbitrary network query params
            # may contain PII, credentials or tracking secrets.
            safe_q = {"subid": sid, "status": st, "payout": payout}
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
            elif st in WAIT and a.status not in (CONFIRMED, PAID, REJECTED, EXPIRED, HOLD):
                o = await s.get(Offer, a.offer_id)
                old_status = a.status
                days = int((a.offer_snapshot or {}).get("hold_days", o.hold))
                a.status, a.hold_until = HOLD, datetime.utcnow() + timedelta(days=days)
                ver = dict(a.verification or {}); ver.setdefault("network_approved", False); a.verification = ver
                s.add(DealEvent(app_id=a.id, actor_id=None, event="network_hold", from_status=old_status, to_status=HOLD, comment=f"Ожидается решение сети; контрольный срок {days} дней; postback status={st}"))
                await s.commit()
                await notify(bot, a.user_id, f"⏳ Сделка #{a.id} принята партнёром в обработку и находится в холде до {a.hold_until:%d.%m.%Y}.")
        return web.json_response({"ok": True})
    app = web.Application(client_max_size=25 * 1024 * 1024)
    app.router.add_get("/postback", pb)
    async def health(req):
        return web.json_response({"ok": True})
    app.router.add_get("/health", health)
    from bot.tma_api import setup_tma
    setup_tma(app, bot)
    return app

def make_scheduler(bot):
    sch = AsyncIOScheduler()
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
    sch.add_job(expire, "interval", minutes=30)
    sch.add_job(remind, "interval", minutes=60)
    sch.add_job(hold_check, "interval", minutes=15)
    return sch
