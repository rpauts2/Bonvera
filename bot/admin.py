from datetime import datetime, timedelta
import asyncio
import csv
import io
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from sqlalchemy import select, func, case
from bot.config import cfg
from bot.db import *
from bot.ui import ik
from bot.logic import notify, mfo_ready, phone_decrypt, confirm
from bot.bonuses import referral_payout_bonus
from bot.proofs import proofs_complete, proof_requirements, awaiting_admin_review
from bot.offer_rules import bk_approval_must_be_reset

r = Router()
class A(StatesGroup):
    rej = State(); needinfo = State(); bc = State(); bc_audience = State(); bc_confirm = State(); url = State(); mfo = State(); appr = State(); edit = State(); verify = State(); notes = State()


def _proof_input(item):
    """Telegram-sendable input for a proof item: TMA storage file or bot file_id."""
    if isinstance(item, dict) and item.get("storage"):
        from bot.tma_files import resolve_proof
        return FSInputFile(resolve_proof(item["storage"]))
    if isinstance(item, dict):
        return item.get("file_id")
    return item

EVENT_RU = {
    "created": "Сделка создана", "proof_uploaded": "Добавлено подтверждение", "proof_submitted": "Комплект передан на проверку",
    "hold_set": "Установлен ручной холд", "network_hold": "Сеть взяла лид на проверку",
    "network_approved_hold": "Сеть подтвердила действие; начался холд",
    "network_rejected": "Сеть отклонила/отозвала лид", "network_payout_received": "Получена сумма выплаты сети",
    "confirmed": "Вознаграждение начислено", "expired": "Истёк срок оформления",
    "hold_elapsed": "Срок холда истёк без ответа сети", "rejected": "Сделка отклонена",
    "admin_comment": "Комментарий администратора", "more_info_requested": "Запрошены дополнительные сведения",
}
PAYOUT_EVENT_RU = {"created":"Создан запрос", "taken":"Взят в обработку", "paid":"Перевод подтверждён",
                   "rejected":"Отклонён с возвратом", "cancelled":"Отменён пользователем", "clawback_cancelled":"Отменён из-за отзыва лида", "review_required":"Требуется сверка после отзыва лида"}
adm = lambda uid: uid in cfg.admins


async def offer_audit(s, offer_id, actor_id, event, details):
    """Store human-readable offer-change history without copying affiliate URL secrets."""
    s.add(OfferEvent(offer_id=offer_id, actor_id=actor_id, event=event, details=(details or "")[:1500]))

@r.message(Command("export"))
async def export_evidence(m: Message, bot: Bot | None = None):
    """Send a private evidence ZIP to an authorized administrator only."""
    if not adm(m.from_user.id):
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        return await m.answer("Использование: /export <id сделки>")
    aid = int(parts[1].strip())
    async with Session() as s:
        app = await s.get(App, aid)
        if app is None:
            return await m.answer(f"Сделка #{aid} не найдена.")
        items = list(app.proof_files or [])
    # Legacy bot uploads are stored as Telegram file_id values; Mini App uploads
    # are private on-disk files. Include both sources in the same archive.
    external_files = []
    unavailable = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("file_id") or item.get("storage"):
            continue
        if bot is None:
            unavailable += 1
            continue
        try:
            telegram_file = await bot.get_file(item["file_id"])
            payload = io.BytesIO()
            await bot.download_file(telegram_file.file_path, destination=payload)
            external_files.append((index, item.get("name") or f"proof-{index + 1}", payload.getvalue()))
        except Exception:
            unavailable += 1
    from bot.tma_files import build_evidence_zip
    archive = build_evidence_zip(items, external_files=external_files)
    if not archive:
        detail = f" Не удалось получить {unavailable} файлов из Telegram." if unavailable else ""
        return await m.answer(f"У сделки #{aid} нет доступных файлов доказательств.{detail}")
    caption = f"Доказательства по сделке #{aid}. Храните архив безопасно: он может содержать персональные данные."
    if unavailable:
        caption += f" Не удалось добавить файлов из Telegram: {unavailable}."
    await m.answer_document(
        BufferedInputFile(archive, filename=f"evidence-{aid}.zip"),
        caption=caption,
    )


@r.message(Command("admin"))
async def panel(m: Message):
    if not adm(m.from_user.id): return
    await m.answer("🛠 <b>Админка</b>", reply_markup=ik(
        [("📥 Скрины", "adm:q"), ("⏳ Холды", "adm:h")],
        [("💸 Запросы на вывод", "adm:p"), ("📚 История выплат", "adm:phistory")],
        [("🗂 Офферы", "adm:o"), ("📜 История сделок", "adm:apps")],
        [("📊 Статистика", "adm:s")],
        [("📣 Рассылка", "adm:bc")],
        [("📤 CSV выплат", "adm:csv")]))

@r.callback_query(F.data == "adm:q")
async def q(c: CallbackQuery, bot: Bot):
    if not adm(c.from_user.id): return
    async with Session() as s:
        candidates = (await s.execute(
            select(App).where(App.status.in_([PROOF, HOLD])).order_by(App.created).limit(200)
        )).scalars().all()
        apps = []
        for candidate in candidates:
            candidate_offer = await s.get(Offer, candidate.offer_id)
            if awaiting_admin_review(candidate, candidate_offer):
                apps.append(candidate)
            if len(apps) >= 10:
                break
        if not apps:
            await c.message.answer("Очередь пуста ✅ Новых комплектов доказательств на проверку нет.")
            return await c.answer()
        for a in apps:
            o = await s.get(Offer, a.offer_id)
            files = list(a.proof_files or [])
            latest = files[-1] if files else {"file_id": a.proof, "kind": "photo"}
            if isinstance(latest, str): latest = {"file_id": latest, "kind": "photo"}
            keyboard = ik([("🔎 Детали сделки", f"adm:deal:{a.id}"), ("📎 Все доказательства", f"adm:proofs:{a.id}")],
                          [("✅ Начислить сейчас", f"adm:confirm:{a.id}"), ("⏳ В холд", f"adm:hold:{a.id}")],
                          [("❌ Отказ с причиной", f"adm:no:{a.id}")])
            try:
                inp = _proof_input(latest) or a.proof
                if latest.get("kind") == "document":
                    await bot.send_document(c.from_user.id, inp, caption=f"#{a.id} · {o.name} · user {a.user_id}", reply_markup=keyboard)
                else:
                    await bot.send_photo(c.from_user.id, inp, caption=f"#{a.id} · {o.name} · user {a.user_id}", reply_markup=keyboard)
            except Exception: await c.message.answer(f"#{a.id} · {o.name} · user {a.user_id} · файл не открылся", reply_markup=keyboard)
    await c.answer()

@r.callback_query(F.data.startswith("adm:confirm:"))
async def manual_confirm(c: CallbackQuery, bot: Bot):
    if not adm(c.from_user.id): return
    aid = int(c.data.split(":")[2])
    async with Session() as s:
        a = (await s.execute(select(App).where(App.id == aid).with_for_update())).scalar_one_or_none()
        if not a or a.status not in (PROOF, HOLD): return await c.answer("Заявка уже обработана или ещё не прислано подтверждение", show_alert=True)
        o = await s.get(Offer, a.offer_id)
        complete, missing = proofs_complete(a, o)
        if not complete:
            return await c.answer("Нельзя начислить: не хватает обязательных доказательств/не отправлен комплект. " + "; ".join(missing[:2]), show_alert=True)
        ts = (await s.execute(select(Tier).where(Tier.offer_id == a.offer_id))).scalars().all()
        if not ts: return await c.answer("У оффера не настроена выплата", show_alert=True)
        credited = await confirm(bot, s, a, None, actor_id=c.from_user.id, comment="Подтверждено администратором вручную")
        if not credited:
            return await c.answer("Сделка уже изменилась или была обработана другим администратором.", show_alert=True)
    if c.message.photo:
        await c.message.edit_caption(caption=f"Заявка #{aid}: подтверждена администратором")
    else:
        await c.message.edit_text(f"Заявка #{aid}: подтверждена администратором")
    await c.answer("Начисление проведено")

@r.callback_query(F.data.startswith("adm:hold:"))
async def to_hold(c: CallbackQuery, bot: Bot):
    if not adm(c.from_user.id): return
    aid = int(c.data.split(":")[2])
    async with Session() as s:
        a = (await s.execute(select(App).where(App.id == aid).with_for_update())).scalar_one_or_none()
        if not a or a.status not in (PROOF, HOLD): return await c.answer("Сначала пользователь должен прислать подтверждение; заявка уже обработана.", show_alert=True)
        if a.status == HOLD and a.hold_until:
            ver = dict(a.verification or {})
            if ver.get("proof_submitted_at"):
                ver["proof_reviewed_at"] = ver["proof_submitted_at"]
                a.verification = ver
                s.add(DealEvent(app_id=a.id, actor_id=c.from_user.id, event="hold_set", from_status=HOLD, to_status=HOLD,
                                comment="Администратор проверил новые доказательства; сделка оставлена в существующем холде без изменения срока"))
                await s.commit()
                return await c.answer(f"Доказательства проверены. Сделка остаётся в холде до {a.hold_until:%d.%m.%Y}; очередь обновлена.", show_alert=True)
            return await c.answer(f"Сделка уже в холде до {a.hold_until:%d.%m.%Y}; срок не изменён.", show_alert=True)
        o = await s.get(Offer, a.offer_id); old = a.status
        days = int((a.offer_snapshot or {}).get("hold_days", o.hold))
        a.status, a.hold_until = HOLD, datetime.utcnow() + timedelta(days=days); a.reviewed_by, a.reviewed_at = c.from_user.id, datetime.utcnow()
        ver = dict(a.verification or {}); ver.setdefault("network_approved", False)
        if ver.get("proof_submitted_at"):
            ver["proof_reviewed_at"] = ver["proof_submitted_at"]
        a.verification = ver
        s.add(DealEvent(app_id=a.id, actor_id=c.from_user.id, event="hold_set", from_status=old, to_status=HOLD, comment=f"Ручной холд {days} дней до {a.hold_until:%Y-%m-%d}; ждём решение сети"))
        await s.commit()
        await notify(bot, a.user_id, f"⏳ Сделка #{a.id} переведена в холд до {a.hold_until:%d.%m.%Y}. Ожидаем подтверждение партнёрской сети.")
    try: await c.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await c.answer("В холде ✅")

@r.callback_query(F.data.startswith("adm:more:"))
async def request_more_info(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    aid = int(c.data.split(":")[2])
    async with Session() as s:
        a = await s.get(App, aid)
        if not a or a.status not in (NEW, PROOF, HOLD):
            return await c.answer("Дополнительные данные можно запросить только по открытой сделке.", show_alert=True)
    await state.set_state(A.needinfo); await state.update_data(aid=aid)
    await c.message.answer(f"Напиши, какие именно сведения/скриншоты нужны по сделке #{aid}. Сообщение отправится пользователю.")
    await c.answer()

@r.message(A.needinfo)
async def request_more_info_do(m: Message, state: FSMContext, bot: Bot):
    if not adm(m.from_user.id): return
    d = await state.get_data(); aid = int(d.get("aid", 0)); note = (m.text or "").strip()
    if not note: return await m.answer("Напиши текстом, какие сведения нужны.")
    if len(note) > 1500: return await m.answer("Сократи сообщение до 1 500 символов.")
    async with Session() as s:
        a = (await s.execute(select(App).where(App.id == aid).with_for_update())).scalar_one_or_none()
        if not a or a.status not in (NEW, PROOF, HOLD):
            await state.clear(); return await m.answer("Сделка уже закрыта; запрос не отправлен.")
        old = a.status
        a.status = HOLD if old == HOLD else PROOF
        ver = dict(a.verification or {})
        ver["more_info_requested_at"] = datetime.utcnow().isoformat()
        ver["more_info_text"] = note
        ver.pop("proof_submitted_at", None)
        ver.pop("proof_reviewed_at", None)
        a.verification = ver
        s.add(DealEvent(app_id=a.id, actor_id=m.from_user.id, event="more_info_requested", from_status=old, to_status=a.status, comment=note))
        await s.commit()
        await notify(bot, a.user_id, f"📝 По сделке #{a.id} нужны дополнительные сведения:\n{note}\n\nОткрой «Мои заявки» → сделка и нажми «Дослать подтверждения».")
    await state.clear(); await m.answer(f"Запрос дополнительных данных по сделке #{aid} отправлен. Сделка возвращена на рассмотрение.")

@r.callback_query(F.data.startswith("adm:no:"))
async def rej(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    await state.set_state(A.rej); await state.update_data(aid=int(c.data.split(":")[2]))
    await c.message.answer("Причина отказа (уйдёт юзеру):"); await c.answer()

@r.message(A.rej)
async def rej_do(m: Message, state: FSMContext, bot: Bot):
    if not adm(m.from_user.id): return
    d = await state.get_data(); await state.clear()
    if d.get("payout_id"):
        pid = int(d["payout_id"])
        async with Session() as s:
            pre = await s.get(PayoutReq, pid)
            if not pre: return await m.answer("Запрос на вывод не найден.")
            u = (await s.execute(select(User).where(User.id == pre.user_id).with_for_update())).scalar_one_or_none()
            p = (await s.execute(select(PayoutReq).where(PayoutReq.id == pid).with_for_update())).scalar_one_or_none()
            if not u or not p or p.status not in ("pending", "processing", "review_required"):
                return await m.answer("Запрос на вывод уже обработан; повторный возврат запрещён.")
            old = p.status; p.status, p.admin_note, p.updated_at, p.processed_by = "rejected", (m.text or "Причина не указана")[:1500], datetime.utcnow(), m.from_user.id
            ref = f"withdraw-refund:{p.id}"
            exists = (await s.execute(select(WalletEntry).where(WalletEntry.ref == ref))).scalar_one_or_none()
            if not exists:
                u.balance += p.amount
                s.add(WalletEntry(user_id=u.id, amount=p.amount, kind="withdraw_refund", ref=ref, note="Возврат отклонённой выплаты"))
            s.add(PayoutEvent(payout_id=p.id, actor_id=m.from_user.id, event="rejected", from_status=old, to_status="rejected", comment=p.admin_note))
            await s.commit()
            await notify(bot, u.id, f"❌ Запрос на вывод #{p.id} отклонён.\nПричина: {p.admin_note}\n{p.amount} ₽ возвращены на доступный баланс.")
        return await m.answer(f"Запрос #{pid} отклонён; средства возвращены.")
    async with Session() as s:
        a = (await s.execute(select(App).where(App.id == d["aid"]).with_for_update())).scalar_one_or_none()
        if not a or a.status in (CONFIRMED, PAID, REJECTED, EXPIRED): return await m.answer("Сделка уже закрыта; изменение отменено.")
        old = a.status; a.status, a.reason = REJECTED, (m.text or "Причина не указана")[:1500]; a.reviewed_by, a.reviewed_at = m.from_user.id, datetime.utcnow()
        s.add(DealEvent(app_id=a.id, actor_id=m.from_user.id, event="rejected", from_status=old, to_status=REJECTED, comment=a.reason))
        await s.commit()
        await notify(bot, a.user_id, f"❌ Сделка #{a.id} отклонена.\nПричина: {a.reason}\nЕсть вопросы? Открой сделку и напиши в поддержку.")
    await m.answer("Отправлено ✅")

@r.callback_query(F.data == "adm:h")
async def holds(c: CallbackQuery):
    if not adm(c.from_user.id): return
    async with Session() as s:
        apps = (await s.execute(select(App).where(App.status == HOLD).order_by(App.hold_until).limit(30))).scalars().all()
        lines = []
        buttons = []
        for a in apps:
            snap = a.offer_snapshot or {}
            end = a.hold_until.strftime("%d.%m.%Y") if a.hold_until else "срок не задан"
            state = "сеть подтвердила" if (a.verification or {}).get("network_approved") else "ждём сеть/ручную проверку"
            lines.append(f"#{a.id} · {snap.get('name','оффер')} · {snap.get('reward',0)} ₽ · до {end} · {state}")
            buttons.append([(f"#{a.id} · {snap.get('name','оффер')[:24]}", f"adm:deal:{a.id}")])
    await c.message.answer("⏳ <b>Холды</b>\n" + ("\n".join(lines) if lines else "пусто"))
    if buttons: await c.message.answer("Открой сделку для доказательств и действий:", reply_markup=ik(*buttons))
    await c.answer()

@r.callback_query(F.data == "adm:p")
async def pays(c: CallbackQuery):
    if not adm(c.from_user.id): return
    async with Session() as s:
        ps = (await s.execute(select(PayoutReq).where(PayoutReq.status.in_(["pending", "processing", "review_required"])).order_by(PayoutReq.created))).scalars().all()
        if not ps: await c.message.answer("Активных запросов на вывод нет."); return await c.answer()
        for p in ps:
            phone = phone_decrypt(p.phone)
            status = {"pending":"🟡 Ожидает обработки", "processing":"🔵 В обработке", "review_required":"🛑 Требуется сверка после отзыва лида"}.get(p.status, p.status)
            if p.status == "pending":
                kb = ik([("▶️ Взять в работу", f"adm:wdtake:{p.id}"), ("❌ Отклонить", f"adm:wdreject:{p.id}")])
            else:
                kb = ik([("✅ Подтвердить фактический перевод", f"adm:paid:{p.id}")], [("❌ Отклонить и вернуть", f"adm:wdreject:{p.id}")])
            await c.message.answer(f"💸 <b>Запрос на вывод #{p.id}</b>\nСумма: <b>{p.amount} ₽</b>\nСтатус: {status}\nБанк: <b>{p.bank or 'не указан'}</b>\nТелефон СБП: <code>{phone}</code>\nUser ID: <code>{p.user_id}</code>\nСоздан: {p.created:%d.%m.%Y %H:%M}", reply_markup=kb)
    await c.answer()

@r.callback_query(F.data.startswith("adm:wdtake:"))
async def payout_take(c: CallbackQuery):
    if not adm(c.from_user.id): return
    pid = int(c.data.split(":")[2])
    async with Session() as s:
        p = (await s.execute(select(PayoutReq).where(PayoutReq.id == pid).with_for_update())).scalar_one_or_none()
        if not p or p.status != "pending": return await c.answer("Запрос уже взят/обработан", show_alert=True)
        p.status, p.processed_by, p.updated_at = "processing", c.from_user.id, datetime.utcnow()
        s.add(PayoutEvent(payout_id=p.id, actor_id=c.from_user.id, event="taken", from_status="pending", to_status="processing", comment="Администратор взял запрос в работу"))
        await s.commit()
        await notify(c.bot, p.user_id, f"🔄 Запрос на вывод #{p.id} взят в обработку. Сумма {p.amount} ₽ зарезервирована.")
    await c.message.edit_reply_markup(reply_markup=ik([("✅ Подтвердить перевод", f"adm:paid:{pid}")], [("❌ Отклонить и вернуть", f"adm:wdreject:{pid}")]))
    await c.answer("Запрос в обработке")

@r.callback_query(F.data.startswith("adm:paid:"))
async def paid(c: CallbackQuery, bot: Bot):
    if not adm(c.from_user.id): return
    pid = int(c.data.split(":")[2])
    async with Session() as s:
        p = (await s.execute(select(PayoutReq).where(PayoutReq.id == pid).with_for_update())).scalar_one_or_none()
        if not p or p.status not in ("processing", "review_required"):
            return await c.answer("Запрос не находится в обработке или уже закрыт.", show_alert=True)
        if p.status == "review_required":
            # This is deliberately a separate manual acknowledgement: after a clawback
            # an operator must confirm that the actual bank transfer was already sent.
            comment = "Фактический перевод в банке проверен администратором после clawback"
        else:
            comment = "Администратор подтвердил фактический перевод"
        old = p.status; p.status, p.paid_at, p.updated_at, p.processed_by = "paid", datetime.utcnow(), datetime.utcnow(), c.from_user.id
        s.add(PayoutEvent(payout_id=p.id, actor_id=c.from_user.id, event="paid", from_status=old, to_status="paid", comment=comment))
        ref_bonus = await referral_payout_bonus(s, p)
        await s.commit()
        await notify(bot, p.user_id, f"💸 <b>Перевод {p.amount} ₽ выполнен</b> по заявке на вывод #{p.id}.")
        if ref_bonus:
            referrer_id, bonus_amount = ref_bonus
            await notify(bot, referrer_id, f"🎁 <b>+{bonus_amount} ₽ за друга!</b> Твой друг получил первую выплату — бонус зачислен в кошелёк.")
    await c.message.edit_text(f"Запрос на вывод #{pid}: перевод отмечен выполненным.")
    await c.answer()

@r.callback_query(F.data.startswith("adm:wdreject:"))
async def payout_reject(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    pid = int(c.data.split(":")[2])
    async with Session() as s:
        p = await s.get(PayoutReq, pid)
        if not p or p.status not in ("pending", "processing", "review_required"): return await c.answer("Запрос уже обработан", show_alert=True)
    await state.set_state(A.rej); await state.update_data(payout_id=pid)
    await c.message.answer(f"Укажи причину отклонения запроса на вывод #{pid}. Деньги будут возвращены на доступный баланс.")
    await c.answer()

@r.callback_query(F.data == "adm:apps")
async def app_queue(c: CallbackQuery):
    if not adm(c.from_user.id): return
    async with Session() as s:
        apps = (await s.execute(select(App).where(App.status.in_([NEW, PROOF, HOLD, CONFIRMED, REJECTED, EXPIRED])).order_by(App.id.desc()).limit(30))).scalars().all()
        rows = []
        for a in apps:
            snap = a.offer_snapshot or {}; title = snap.get("name", f"оффер {a.offer_id}")
            rows.append([(f"#{a.id} · {title[:22]} · {RU.get(a.status,a.status)}", f"adm:deal:{a.id}")])
    await c.message.answer("📜 <b>Последние сделки</b>")
    for i in range(0, len(rows), 40): await c.message.answer("Открой сделку:", reply_markup=ik(*rows[i:i+40]))
    if not rows: await c.message.answer("Сделок пока нет.")
    await c.answer()

@r.callback_query(F.data.startswith("adm:deal:"))
async def deal_detail(c: CallbackQuery):
    if not adm(c.from_user.id): return
    aid = int(c.data.split(":")[2])
    async with Session() as s:
        a = await s.get(App, aid)
        if not a: return await c.answer("Сделка не найдена", show_alert=True)
        u = await s.get(User, a.user_id); snap = a.offer_snapshot or {}
        events = (await s.execute(select(DealEvent).where(DealEvent.app_id==aid).order_by(DealEvent.created))).scalars().all()
        ev = "\n".join(f"{e.created:%d.%m %H:%M} · {EVENT_RU.get(e.event, 'Изменение')}: {e.comment}" for e in events) or "Событий пока нет"
        hold_until_text = a.hold_until.strftime("%d.%m.%Y %H:%M") if a.hold_until else "не установлен"
        txt = (f"🧾 <b>Сделка #{aid}</b>\nПользователь: {u.name or '—'} (@{u.username or '—'}) · <code>{u.id}</code>\n"
               f"Оффер: {snap.get('brand','')} · {snap.get('name','—')} ({snap.get('code','—')})\nУсловие на момент создания: {snap.get('condition','—')}\n"
               f"Особые условия акции на момент создания: {snap.get('promo_notes') or '—'}\nИсточник правил: {snap.get('source_url') or '—'}\n"
               f"Награда: {snap.get('reward',a.cashback)} ₽ · Холд: {snap.get('hold_days','—')} дн.\nСтатус: <b>{RU.get(a.status,a.status)}</b>\n"
               f"Выплата от партнёрской сети: {a.payout} ₽ · Начислено пользователю: {a.cashback} ₽\nХолд до: {hold_until_text} · сеть подтвердила: {'да' if (a.verification or {}).get('network_approved') else 'нет'}\nПричина отказа: {a.reason or '—'}\n"
               f"Файлов подтверждения: {len(a.proof_files or [])}\n\n<b>История:</b>\n{ev}")
        requirements = proof_requirements(a, await s.get(Offer, a.offer_id))
        proof_items = [x for x in (a.proof_files or []) if isinstance(x, dict)]
        received_idx = {int(x["proof_index"]) for x in proof_items if x.get("proof_index") is not None}
        if requirements:
            checklist = "\n".join(("✅ " if i in received_idx else "⬜ ") + f"{i+1}. {label}" for i, label in enumerate(requirements))
            txt += "\n\n<b>Чек-лист доказательств:</b>\n" + checklist
        if proof_items:
            txt += "\n\n<b>Приложенные файлы:</b>\n" + "\n".join(
                f"• {x.get('label','Доп. файл')} · {x.get('uploaded_at','')[:16]}" + (" ⚠️ ПОХОЖ НА ДРУГОЙ СКРИН — проверить вручную" if x.get("duplicate_suspected") else "")
                for x in proof_items
            )
    buttons = [[("📎 Просмотреть доказательства", f"adm:proofs:{aid}")]]
    if a.status in (NEW, PROOF, HOLD):
        buttons.append([("📝 Запросить дополнительные данные", f"adm:more:{aid}")])
        buttons.append([("✅ Начислить сейчас", f"adm:confirm:{aid}"), ("⏳ В холд", f"adm:hold:{aid}")])
        buttons.append([("❌ Отклонить с причиной", f"adm:no:{aid}")])
    buttons.append([("📥 Очередь проверки", "adm:q")])
    await c.message.answer(txt, reply_markup=ik(*buttons))
    await c.answer()

@r.callback_query(F.data.startswith("adm:proofs:"))
async def view_proofs(c: CallbackQuery, bot: Bot):
    if not adm(c.from_user.id): return
    aid = int(c.data.split(":")[2])
    async with Session() as s:
        a = await s.get(App, aid)
        if not a: return await c.answer("Сделка не найдена", show_alert=True)
        items = list(a.proof_files or [])
        if not items and a.proof: items = [{"file_id": a.proof, "kind": "photo"}]
    if not items: return await c.answer("Доказательства ещё не загружены", show_alert=True)
    await c.answer(f"Отправляю файлов: {len(items)}")
    for i, item in enumerate(items, 1):
        if isinstance(item, str): item = {"file_id": item, "kind": "photo"}
        try:
            inp = _proof_input(item)
        except Exception:
            inp = None
        if not inp: continue
        caption = f"Сделка #{aid} · {item.get('label', f'доказательство {i}/{len(items)}')}"
        if item.get("duplicate_suspected"):
            caption += "\n⚠️ Похожий файл найден в других доказательствах; проверь вручную."
        if item.get("kind") == "document": await bot.send_document(c.from_user.id, inp, caption=caption)
        else: await bot.send_photo(c.from_user.id, inp, caption=caption)

@r.callback_query(F.data == "adm:phistory")
async def payout_history(c: CallbackQuery):
    if not adm(c.from_user.id): return
    status_ru = {"pending":"ожидает", "processing":"в обработке", "review_required":"требуется сверка", "paid":"выплачено", "rejected":"отклонено", "cancelled":"отменено"}
    async with Session() as s:
        rows = (await s.execute(select(PayoutReq).order_by(PayoutReq.id.desc()).limit(25))).scalars().all()
        events_by_id = {}
        for p in rows:
            evs = (await s.execute(select(PayoutEvent).where(PayoutEvent.payout_id == p.id).order_by(PayoutEvent.created.desc()).limit(5))).scalars().all()
            events_by_id[p.id] = evs
    if not rows: await c.message.answer("История выплат пока пуста."); return await c.answer()
    await c.message.answer("📚 <b>История запросов на вывод</b>")
    for p in rows:
        ev = "\n".join(f"{x.created:%d.%m %H:%M} · {PAYOUT_EVENT_RU.get(x.event, 'Изменение')}: {x.comment}" for x in reversed(events_by_id[p.id])) or "Событий нет"
        phone = phone_decrypt(p.phone)
        await c.message.answer(f"<b>Вывод #{p.id}</b> · {p.amount} ₽ · {status_ru.get(p.status,p.status)}\nБанк: {p.bank or '—'} · СБП: <code>{phone}</code>\nПользователь: <code>{p.user_id}</code>\nКомментарий: {p.admin_note or '—'}\n\n<b>Хронология:</b>\n{ev}")
    await c.answer()

@r.callback_query(F.data == "adm:o")
async def offers(c: CallbackQuery):
    if not adm(c.from_user.id): return
    async with Session() as s:
        os_ = (await s.execute(select(Offer).order_by(Offer.bank_id, Offer.id))).scalars().all()
        rows = [[(f"{'🟢' if o.enabled else '🔴'} {o.name[:30]} · {o.code[:14]}", f"adm:t:{o.id}")] for o in os_]
    await c.message.answer(f"🗂 <b>Офферы</b> · всего {len(rows)}. Список разбит на сообщения.")
    for start in range(0, len(rows), 45):
        await c.message.answer("Выбери оффер:", reply_markup=ik(*rows[start:start+45]))
    await c.answer()

@r.callback_query(F.data.startswith("adm:t:"))
async def offer_adm(c: CallbackQuery):
    if not adm(c.from_user.id): return
    oid = int(c.data.split(":")[2])
    async with Session() as s:
        o = await s.get(Offer, oid); bk = await s.get(Bank, o.bank_id)
        t = (await s.execute(select(Tier).where(Tier.offer_id == oid))).scalars().all()
        money = " / ".join(f"{x.payout if x.payout > 0 else 'не задана'} → {x.cashback}" for x in t)
        network_ru = {"needs_approval":"требует согласования", "approved":"согласовано", "rejected":"запрещено", "paused":"приостановлено"}.get(o.network_status, "не проверено")
        txt = (f"{bk.emoji} <b>{bk.name} · {o.name}</b>\n{CAT_RU[bk.category]} · код <code>{o.code}</code>\n"
               f"Сеть (факт из postback) → награда пользователю: {money}\nХолд {o.hold}д · возраст {o.age_min}–{o.age_max if o.age_max < 120 else 'без верхнего ограничения'}\n"
               f"Условие: {o.condition_text or o.action}\nСсылка: {'есть' if o.url else '❌ НЕТ'}\n"
               f"Статус согласования: {network_ru}\nЗапреты: {', '.join(o.forbidden) or '—'}\n"
               f"Согласование: {o.approval or '—'}\nИсточник: {o.source_url or 'не указан'}\nПримечание/бонус БК: {o.notes or '—'}\n"
               f"Проверено: {o.terms_checked_at or 'ещё не проверено'}\nСтатус витрины: {'🟢 включён' if o.enabled else '🔴 выключен'}")
        if bk.category == "mfo": txt += f"\nПСК/ставка/срок/реестр: {'✅' if mfo_ready(o) else '❌ не заполнены'}"
        audit_rows = (await s.execute(select(OfferEvent).where(OfferEvent.offer_id == oid).order_by(OfferEvent.created.desc()).limit(8))).scalars().all()
        if audit_rows:
            txt += "\n\n<b>История изменений:</b>\n" + "\n".join(
                f"{ev.created:%d.%m %H:%M} · admin {ev.actor_id or 'system'} · {ev.details}" for ev in reversed(audit_rows)
            )
    await c.message.edit_text(txt, reply_markup=ik(
        [("🔴 Выключить" if o.enabled else "🟢 Включить", f"adm:sw:{oid}"), ("🔗 Ссылка", f"adm:url:{oid}")],
        [("📊 ПСК (МФО)", f"adm:mfo:{oid}"), ("✅ Согласовано", f"adm:ap:{oid}")],
        [("✏️ Изменить условия/выплаты", f"adm:edit:{oid}")],
        [("🧾 Настроить проверку/скрины", f"adm:verify:{oid}")],
        [("🎁 Изменить бонус/примечание", f"adm:notes:{oid}")],
        [("⬅️ К списку", "adm:o")]))
    await c.answer()

@r.callback_query(F.data.startswith("adm:sw:"))
async def switch(c: CallbackQuery):
    if not adm(c.from_user.id): return
    oid = int(c.data.split(":")[2])
    async with Session() as s:
        o = await s.get(Offer, oid); bk = await s.get(Bank, o.bank_id)
        o.enabled = not o.enabled; st = o.enabled
        await offer_audit(s, o.id, c.from_user.id, "toggle", "Оффер " + ("включён" if st else "выключен") + " в каталоге")
        await s.commit()
    await c.answer("🟢 включён" if st else "🔴 выключен")

@r.callback_query(F.data.startswith("adm:url:"))
async def set_url(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    await state.set_state(A.url); await state.update_data(oid=int(c.data.split(":")[2]))
    await c.message.answer("Пришли партнёрскую ссылку:"); await c.answer()
@r.message(A.url)
async def url_do(m: Message, state: FSMContext):
    if not adm(m.from_user.id): return
    d = await state.get_data(); await state.clear()
    new_url = (m.text or "").strip()
    if not new_url.startswith(("https://", "http://")):
        return await m.answer("Нужна полная ссылка, начинающаяся с https:// или http://")
    async with Session() as s:
        o = await s.get(Offer, d["oid"]); bk = await s.get(Bank, o.bank_id)
        old_url = o.url or ""
        o.url = new_url
        if bk.category == "bk" and old_url != new_url:
            o.network_status = "needs_approval"
            o.approval = "Старое согласование требует повторной проверки после изменения партнёрской ссылки."
            o.terms_checked_at = None
        await offer_audit(s, o.id, m.from_user.id, "link_changed", "Партнёрская ссылка обновлена" + ("; письменное согласование БК сброшено" if bk.category == "bk" and old_url != new_url else ""))
        await s.commit()
    await m.answer("Ссылка сохранена ✅" + (" Для БК согласование сброшено — подтверди новую ссылку письменно." if bk.category == "bk" and old_url != new_url else ""))

@r.callback_query(F.data.startswith("adm:mfo:"))
async def set_mfo(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    await state.set_state(A.mfo); await state.update_data(oid=int(c.data.split(":")[2]))
    await c.message.answer("Одной строкой через | : ПСК | ставка | срок | № реестра ЦБ\nПример: 292% | 0,8%/день | 5-30 дней | 1234"); await c.answer()
@r.message(A.mfo)
async def mfo_do(m: Message, state: FSMContext):
    if not adm(m.from_user.id): return
    d = await state.get_data(); await state.clear()
    p = [x.strip() for x in m.text.split("|")]
    if len(p) != 4: return await m.answer("Нужно 4 значения через |")
    async with Session() as s:
        o = await s.get(Offer, d["oid"])
        o.mfo_info = dict(psk=p[0], rate=p[1], term=p[2], registry=p[3])
        await offer_audit(s, o.id, m.from_user.id, "mfo_terms_changed", "Обновлены ПСК, ставка, срок и номер записи в реестре")
        await s.commit()
    await m.answer("Условия займа сохранены ✅")

@r.callback_query(F.data.startswith("adm:ap:"))
async def set_ap(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    await state.set_state(A.appr); await state.update_data(oid=int(c.data.split(":")[2]))
    await c.message.answer("Кто и когда согласовал (например: менеджер Иван, 13.11.2026, кешбэк разрешён):"); await c.answer()
@r.message(A.appr)
async def ap_do(m: Message, state: FSMContext):
    if not adm(m.from_user.id): return
    d = await state.get_data(); await state.clear()
    async with Session() as s:
        o = await s.get(Offer, d["oid"]); o.approval = m.text[:200]; o.network_status = "approved"; o.terms_checked_at = datetime.utcnow()
        await offer_audit(s, o.id, m.from_user.id, "approval_recorded", "Записано письменное согласование: " + m.text[:300])
        await s.commit()
    await m.answer("Согласование записано. Проверь ссылку, сумму сети, кэшбэк и условия перед запуском трафика.")

@r.callback_query(F.data.startswith("adm:edit:"))
async def edit_offer(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    oid = int(c.data.split(":")[2])
    async with Session() as s:
        o = await s.get(Offer, oid)
        t = (await s.execute(select(Tier).where(Tier.offer_id == oid))).scalars().first()
        values = f"{o.name} | {o.condition_text or o.action} | {t.payout if t else 0} | {t.cashback if t else 0} | {o.hold} | {o.purchase_min} | {o.age_min}-{o.age_max} | {o.link_param} | {o.url} | {o.source_url}"
    await state.set_state(A.edit); await state.update_data(oid=oid)
    await c.message.answer("Пришли одной строкой 10 полей через |\nНазвание | условие | выплата сети ₽ (0 если неизвестна) | награда пользователю ₽ | холд дней | минимум покупки/депозита ₽ | возраст (18-120) | параметр метки | партнёрская ссылка | официальные правила\n\nТекущие значения:\n" + values + "\n\nЕсли ссылка пока не согласована, оставь последнее поле пустым.")
    await c.answer()

@r.message(A.edit)
async def edit_offer_do(m: Message, state: FSMContext):
    if not adm(m.from_user.id): return
    parts = [x.strip() for x in (m.text or "").split("|")]
    if len(parts) != 10:
        return await m.answer("Нужно ровно 10 полей, разделённых символом |. Попробуй ещё раз.")
    try:
        payout, cashback, hold, minimum = [int(x) for x in parts[2:6]]
        age_min, age_max = [int(x) for x in parts[6].replace("–", "-").split("-", 1)]
    except ValueError: return await m.answer("Суммы/холд/минимум должны быть числами, возраст — например 18-75.")
    if min(payout, cashback, hold, minimum) < 0 or cashback == 0 or hold > 365 or age_min < 18 or age_max < age_min or age_max > 120:
        return await m.answer("Награда пользователю должна быть больше 0; выплата сети может быть 0 (неизвестна). Холд 0–365 дней, возраст 18–120.")
    if parts[8] and not parts[8].startswith(("https://", "http://")):
        return await m.answer("Партнёрская ссылка должна начинаться с https:// или http://")
    d = await state.get_data()
    async with Session() as s:
        o = await s.get(Offer, d["oid"])
        bk = await s.get(Bank, o.bank_id)
        tier_before = (await s.execute(select(Tier).where(Tier.offer_id == o.id).order_by(Tier.id))).scalars().first()
        before = {
            "name": o.name, "condition": o.condition_text or o.action,
            "network_payout": tier_before.payout if tier_before else 0,
            "user_reward": tier_before.cashback if tier_before else 0,
            "hold_days": o.hold, "minimum": o.purchase_min,
            "age_min": o.age_min, "age_max": o.age_max,
            "tracking_param": o.link_param, "partner_url": o.url,
            "source_url": o.source_url,
        }
        after = {
            "name": parts[0][:160], "condition": parts[1],
            "network_payout": payout, "user_reward": cashback,
            "hold_days": hold, "minimum": minimum,
            "age_min": age_min, "age_max": age_max,
            "tracking_param": parts[7][:40] or "subid", "partner_url": parts[8],
            "source_url": parts[9],
        }
        reset_bk_approval = bk_approval_must_be_reset(bk.category, before, after)
        o.name, o.condition_text, o.action = parts[0][:160], parts[1], parts[1]
        o.link_param = parts[7][:40] or "subid"
        o.url, o.source_url = parts[8], parts[9]
        o.hold, o.purchase_min, o.age = hold, minimum, age_min
        o.age_min, o.age_max = age_min, age_max
        ts = (await s.execute(select(Tier).where(Tier.offer_id == o.id))).scalars().all()
        if ts:
            ts[0].payout, ts[0].cashback = payout, cashback
            for extra in ts[1:]: await s.delete(extra)
        else: s.add(Tier(offer_id=o.id, payout=payout, cashback=cashback))
        if reset_bk_approval:
            o.network_status = "needs_approval"
            o.approval = "Старое согласование сброшено после изменения существенных условий. Требуется повторное письменное подтверждение."
            o.terms_checked_at = None
        await offer_audit(s, o.id, m.from_user.id, "terms_changed", "Изменены поля оффера: " + ", ".join(
            key for key in before if before.get(key) != after.get(key)
        ) + ("; повторное согласование БК обязательно" if reset_bk_approval else ""))
        await s.commit()
    await state.clear(); await m.answer("Карточка оффера обновлена. Ссылка, условия, суммы и холд сохранены." + (" Согласование БК сброшено — до нового письменного подтверждения сделки недоступны." if reset_bk_approval else ""))

@r.callback_query(F.data.startswith("adm:notes:"))
async def edit_notes(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    oid = int(c.data.split(":")[2])
    async with Session() as s:
        o = await s.get(Offer, oid)
        current = o.notes or ""
    await state.set_state(A.notes); await state.update_data(oid=oid)
    await c.message.answer("Отправь текст отдельного бонуса БК / примечания для карточки пользователя. Чтобы очистить, отправь дефис (-).\n\nСейчас:\n" + (current or "—"))
    await c.answer()

@r.message(A.notes)
async def edit_notes_do(m: Message, state: FSMContext):
    if not adm(m.from_user.id): return
    d = await state.get_data(); value = (m.text or "").strip()
    if len(value) > 2500: return await m.answer("Слишком длинно: максимум 2500 символов.")
    async with Session() as s:
        o = await s.get(Offer, d["oid"]); o.notes = "" if value == "-" else value
        await offer_audit(s, o.id, m.from_user.id, "promo_notes_changed", "Обновлено примечание/описание отдельного бонуса")
        await s.commit()
    await state.clear(); await m.answer("Примечание/описание бонуса сохранено. Оно появится в карточке оффера.")

@r.callback_query(F.data.startswith("adm:verify:"))
async def verify_offer(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    oid = int(c.data.split(":")[2])
    await state.set_state(A.verify); await state.update_data(oid=oid)
    await c.message.answer("Отправь два блока, разделив их пустой строкой.\n\nБлок 1 — шаги выполнения/проверки, каждый с новой строки.\nБлок 2 — какие скриншоты нужны, каждый с новой строки.\n\nПример:\nРегистрация по ссылке\nКарта выдана\nПокупка от 500 ₽\n\nСкрин выпуска карты (личные данные скрыть)\nСкрин операции с датой и суммой")
    await c.answer()

@r.message(A.verify)
async def verify_offer_do(m: Message, state: FSMContext):
    if not adm(m.from_user.id): return
    blocks = (m.text or "").split("\n\n", 1)
    if len(blocks) != 2: return await m.answer("Нужно два блока текста, разделённых пустой строкой.")
    steps = [x.strip(" •-\t") for x in blocks[0].splitlines() if x.strip()]
    proofs = [x.strip(" •-\t") for x in blocks[1].splitlines() if x.strip()]
    if not steps or not proofs: return await m.answer("Оба блока должны содержать хотя бы один пункт.")
    d = await state.get_data()
    async with Session() as s:
        o = await s.get(Offer, d["oid"]); o.verification_steps = steps; o.required_proofs = proofs
        await offer_audit(s, o.id, m.from_user.id, "proof_template_changed", f"Обновлены шаги проверки ({len(steps)}) и пункты доказательств ({len(proofs)})")
        await s.commit()
    await state.clear(); await m.answer("Сценарий проверки и список доказательств сохранены.")

@r.callback_query(F.data == "adm:csv")
async def export_csv(c: CallbackQuery):
    if not adm(c.from_user.id): return
    # The export contains decrypted payout phone numbers. Keep it in memory only:
    # never leave a plaintext payment registry on the server filesystem.
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["ID", "Telegram ID", "Сумма", "Статус", "Банк СБП", "Создана", "Обновлена", "Оплачена", "Телефон СБП", "Комментарий"])
    async with Session() as s:
        rows = (await s.execute(select(PayoutReq).order_by(PayoutReq.id.desc()))).scalars().all()
        for p in rows:
            writer.writerow([p.id, p.user_id, p.amount, p.status, p.bank, p.created, p.updated_at, p.paid_at, phone_decrypt(p.phone), p.admin_note])
    payload = buffer.getvalue().encode("utf-8-sig")
    document = BufferedInputFile(payload, filename=f"payments-{datetime.utcnow():%Y%m%d-%H%M%S}.csv")
    await c.message.answer_document(document, caption="Реестр выплат CSV. Храните файл безопасно: внутри есть платёжные данные.")
    await c.answer("Экспорт готов")

@r.callback_query(F.data == "adm:s")
async def stats(c: CallbackQuery):
    if not adm(c.from_user.id): return
    async with Session() as s:
        u = (await s.execute(select(func.count(User.id)))).scalar() or 0
        by = dict((await s.execute(select(App.status, func.count(App.id)).group_by(App.status))).all())
        total_apps = sum(by.values())
        completed_apps = int(by.get(CONFIRMED, 0) or 0) + int(by.get(PAID, 0) or 0)
        conversion = round(completed_apps * 100 / total_apps, 1) if total_apps else 0
        inc = (await s.execute(select(func.coalesce(func.sum(App.payout), 0)).where(App.status.in_([CONFIRMED, PAID])))).scalar() or 0
        out = (await s.execute(select(func.coalesce(func.sum(App.cashback), 0)).where(App.status.in_([CONFIRMED, PAID])))).scalar() or 0
        referral_commission = (await s.execute(select(func.coalesce(func.sum(RefAcc.amount), 0)))).scalar() or 0
        first_payout_bonuses = (await s.execute(
            select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(WalletEntry.kind == "task_ref_bonus")
        )).scalar() or 0
        refs = int(referral_commission) + int(first_payout_bonuses)
        wd = (await s.execute(select(func.coalesce(func.sum(PayoutReq.amount), 0)).where(PayoutReq.status == "paid"))).scalar() or 0
        pending_wd = (await s.execute(select(func.coalesce(func.sum(PayoutReq.amount), 0)).where(PayoutReq.status.in_(["pending", "processing", "review_required"])))).scalar() or 0
        hold_sum = (await s.execute(select(func.coalesce(func.sum(App.cashback), 0)).where(App.status == HOLD))).scalar() or 0
        offer_rows = (await s.execute(
            select(
                Offer.name,
                func.count(App.id),
                func.sum(case((App.status.in_([CONFIRMED, PAID]), 1), else_=0)),
                func.coalesce(func.sum(case((App.status.in_([CONFIRMED, PAID]), App.payout), else_=0)), 0),
                func.coalesce(func.sum(case((App.status.in_([CONFIRMED, PAID]), App.cashback), else_=0)), 0),
            )
            .join(App, App.offer_id == Offer.id)
            .group_by(Offer.id, Offer.name)
            .order_by(func.count(App.id).desc(), Offer.name)
            .limit(8)
        )).all()
    status_ru = {NEW:"оформляются", PROOF:"на проверке", HOLD:"в холде", CONFIRMED:"подтверждены", PAID:"выплачены", REJECTED:"отклонены", EXPIRED:"истекли"}
    by_ru = ", ".join(f"{status_ru.get(k,k)}: {v}" for k,v in by.items()) or "нет заявок"
    margin_text = (f"Предварительная разница по учтённой комиссии: {inc - out - refs} ₽\n"
                   "(до расходов; учтённая комиссия не равна подтверждённому поступлению денег)."
                   if inc > 0 else "Предварительную маржу пока нельзя оценить: нет учтённой комиссии сети.")
    offer_lines = []
    for name, total, completed, network_sum, user_sum in offer_rows:
        short_name = (name or "Без названия").replace("\n", " ")[:36]
        offer_lines.append(
            f"• {short_name}: {total} заяв. · {completed or 0} подтв. · "
            f"сеть {network_sum} ₽ · пользователям {user_sum} ₽"
        )
    offer_stats = "\n".join(offer_lines) if offer_lines else "Пока нет заявок по офферам."
    await c.message.answer(
        f"📊 <b>Показатели BONVERA</b>\n"
        f"Пользователей: {u}\n"
        f"Всего заявок: {total_apps} · подтверждено/выплачено: {completed_apps} ({conversion}%)\n"
        f"Статусы: {by_ru}\n\n"
        f"💼 <b>Деньги</b>\n"
        f"Комиссии сети по postback: {inc} ₽\n"
        f"Вознаграждения пользователям: {out} ₽\n"
        f"Реферальные начисления: {refs} ₽\n"
        f"Сумма в холде: {hold_sum} ₽\n"
        f"Ожидают обработки на вывод: {pending_wd} ₽\n"
        f"Фактически отмечено выплаченным: {wd} ₽\n"
        f"{margin_text}\n\n"
        f"🏷 <b>Офферы по числу заявок (топ-8)</b>\n{offer_stats}"
    )
    await c.answer()

def broadcast_keyboard():
    """Every campaign copy gets a direct Mini App launch button."""
    if not cfg.webapp_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Перейти в Bonvera", web_app=WebAppInfo(url=cfg.webapp_url))
    ]])


def broadcast_audience_query(audience: str):
    query = select(User.id).where(User.banned == False)
    if audience == "accepted":
        query = query.where(User.accepted == True)
    return query.order_by(User.id)


@r.callback_query(F.data == "adm:bc")
async def bc(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    if not cfg.webapp_url:
        await c.answer("Сначала настрой WEBAPP_URL — без него нельзя добавить кнопку перехода.", show_alert=True)
        return
    await state.set_state(A.bc)
    await c.message.answer(
        "📣 <b>Новая рассылка</b>\n\n"
        "Отправь следующим сообщением готовую публикацию: текст, фото с подписью, видео или документ.\n"
        "Форматирование и вложения сохранятся. Перед отправкой будет предпросмотр и подтверждение."
    )
    await c.answer()


@r.message(A.bc)
async def bc_do(m: Message, state: FSMContext, bot: Bot):
    if not adm(m.from_user.id): return
    if not any((m.text, m.caption, m.photo, m.video, m.document, m.animation, m.audio, m.voice, m.video_note)):
        return await m.answer("Не удалось распознать публикацию. Отправь текст или медиафайл с подписью.")
    await state.update_data(source_chat_id=m.chat.id, source_message_id=m.message_id)
    await state.set_state(A.bc_audience)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Все пользователи", callback_data="bc:audience:all")],
        [InlineKeyboardButton(text="Приняли правила 18+", callback_data="bc:audience:accepted")],
        [InlineKeyboardButton(text="Отмена", callback_data="bc:cancel")],
    ])
    try:
        await bot.copy_message(chat_id=m.chat.id, from_chat_id=m.chat.id, message_id=m.message_id,
                                reply_markup=broadcast_keyboard())
    except Exception as exc:
        await state.clear()
        return await m.answer(f"Предпросмотр не удалось скопировать ({type(exc).__name__}). Рассылка не запущена.")
    await m.answer("Выбери аудиторию для публикации:", reply_markup=keyboard)


@r.callback_query(F.data.startswith("bc:audience:"))
async def bc_audience(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    if await state.get_state() != A.bc_audience.state:
        return await c.answer("Сессия рассылки устарела. Начни заново через /admin.", show_alert=True)
    audience = c.data.rsplit(":", 1)[-1]
    if audience not in {"all", "accepted"}:
        return await c.answer("Неизвестная аудитория.", show_alert=True)
    await state.update_data(audience=audience)
    await state.set_state(A.bc_confirm)
    async with Session() as s:
        conditions = [User.banned == False]
        if audience == "accepted":
            conditions.append(User.accepted == True)
        count = (await s.execute(select(func.count(User.id)).where(*conditions))).scalar_one()
    label = "принявшим правила 18+" if audience == "accepted" else "всем незаблокированным пользователям"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🚀 Отправить ({count})", callback_data="bc:send")],
        [InlineKeyboardButton(text="Отмена", callback_data="bc:cancel")],
    ])
    await c.message.answer(f"Получатели: <b>{label}</b>.\nКоличество: <b>{count}</b>.\nПодтвердить рассылку?", reply_markup=keyboard)
    await c.answer()


@r.callback_query(F.data == "bc:send")
async def bc_send(c: CallbackQuery, state: FSMContext, bot: Bot):
    if not adm(c.from_user.id): return
    if await state.get_state() != A.bc_confirm.state:
        return await c.answer("Нет активной рассылки. Начни заново через /admin.", show_alert=True)
    data = await state.get_data()
    if not cfg.webapp_url:
        await state.clear()
        return await c.answer("WEBAPP_URL не настроен. Рассылка отменена.", show_alert=True)
    async with Session() as s:
        ids = (await s.execute(broadcast_audience_query(data.get("audience", "all")))).scalars().all()
        campaign = BroadcastCampaign(
            admin_id=c.from_user.id,
            source_chat_id=int(data["source_chat_id"]),
            source_message_id=int(data["source_message_id"]),
            audience=data.get("audience", "all"),
            recipient_count=len(ids),
        )
        s.add(campaign)
        await s.commit()
        campaign_id = campaign.id
    await state.clear()
    sent = failed = 0
    status = await c.message.answer(f"Рассылка запущена: 0/{len(ids)}")
    for uid in ids:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=int(data["source_chat_id"]),
                                   message_id=int(data["source_message_id"]),
                                   reply_markup=broadcast_keyboard())
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    async with Session() as s:
        campaign = await s.get(BroadcastCampaign, campaign_id)
        if campaign:
            campaign.sent_count = sent
            campaign.failed_count = failed
            await s.commit()
    await status.edit_text(f"✅ <b>Рассылка завершена</b>\nУспешно: {sent}\nНе доставлено: {failed}\nВсего: {len(ids)}")
    await c.answer("Готово")


@r.callback_query(F.data == "bc:cancel")
async def bc_cancel(c: CallbackQuery, state: FSMContext):
    if not adm(c.from_user.id): return
    await state.clear()
    await c.message.answer("Рассылка отменена. Ничего не отправлено.")
    await c.answer()

@r.message(Command("reply"))
async def reply(m: Message, bot: Bot):
    if not adm(m.from_user.id): return
    p = m.text.split(" ", 2)
    if len(p) < 3: return await m.answer("/reply <id> <текст>")
    await notify(bot, int(p[1]), f"🆘 <b>Поддержка:</b>\n{p[2]}"); await m.answer("Отправлено ✅")

@r.message(Command("enable_all"))
async def en_all(m: Message):
    if not adm(m.from_user.id): return
    async with Session() as s:
        n = sk = 0
        for o in (await s.execute(select(Offer))).scalars().all():
            bk = await s.get(Bank, o.bank_id)
            o.enabled = True; n += 1
        await s.commit()
    await m.answer(f"🟢 Включено {n}, пропущено {sk} (нет ссылки / ПСК / согласования).")

@r.message(Command("disable_unapproved"))
async def dis(m: Message):
    if not adm(m.from_user.id): return
    async with Session() as s:
        n = 0
        for o in (await s.execute(select(Offer))).scalars().all():
            if o.forbidden or not o.url or not o.approval:
                o.enabled = False; n += 1
        await s.commit()
    await m.answer(f"🔴 Выключено {n}.")

@r.message(Command("ban"))
async def ban(m: Message):
    if not adm(m.from_user.id): return
    uid = int(m.text.split()[1])
    async with Session() as s:
        u = await s.get(User, uid)
        if u: u.banned = not u.banned; await s.commit(); return await m.answer(f"{'🚫 забанен' if u.banned else '✅ разбанен'} {uid}")
    await m.answer("Не найден")
