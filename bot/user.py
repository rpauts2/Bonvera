from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from pathlib import Path
from io import BytesIO
import imagehash
import uuid
from PIL import Image
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from bot.config import cfg
from bot import services
from bot.db import *
from bot.ui import *
from bot.logic import *

r = Router()
class St(StatesGroup):
    proof = State(); wd_amt = State(); wd_phone = State(); sup = State(); age = State(); sbp_bank = State(); sbp_phone = State()

async def uget(s, m):
    u = await s.get(User, m.from_user.id)
    if not u:
        u = User(id=m.from_user.id, username=m.from_user.username, name=m.from_user.first_name)
        s.add(u); await s.commit()
    return u

async def send_webapp_button(m: Message):
    # Inline web_app button: Telegram signs initData for this launch path.
    # A reply-keyboard web_app button would open the app with EMPTY initData.
    if not cfg.webapp_url:
        return
    kb = start_kb(m.from_user.id)
    await m.answer("📱 <b>Приложение BONVERA</b> — каталог, заявки, кошелёк и бонусы:", reply_markup=kb)

@r.message(CommandStart())
async def start(m: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    async with Session() as s:
        u = await uget(s, m)
        if u.banned: return await m.answer("🚫 Доступ ограничен.")
        if command.args and command.args.startswith("ref_") and not u.referrer_id:
            try:
                rid = int(command.args[4:])
                if rid != u.id and await s.get(User, rid): u.referrer_id = rid; await s.commit()
            except ValueError: pass
        if not u.accepted:
            return await m.answer(WELCOME, reply_markup=ik([("✅ Принимаю, мне 18+", "accept")]))
    await m.answer(START_PITCH, reply_markup=MENU)
    await send_webapp_button(m)

@r.callback_query(F.data == "accept")
async def accept(c: CallbackQuery):
    async with Session() as s:
        u = await s.get(User, c.from_user.id); u.accepted = u.adult = True; await s.commit()
    await c.message.edit_text("Готово ✅"); await c.message.answer("Выбирай раздел 👇", reply_markup=MENU); await c.answer()
    await send_webapp_button(c.message)

GATES = {"bk": ("⚽ Ставки", cfg.bk, BK_GATE), "mfo": ("🏦 Займы", cfg.mfo, MFO_GATE), "cpl": ("📝 Заявки", cfg.cpl, CPL_GATE)}

async def banks_view(m: Message, cat):
    async with Session() as s:
        bs = (await s.execute(select(Bank).where(Bank.category == cat).order_by(Bank.sort))).scalars().all()
        b = InlineKeyboardBuilder()
        for bk in bs:
            os_ = (await s.execute(select(Offer).where(Offer.bank_id == bk.id, Offer.enabled == True))).scalars().all()
            
            if not os_: continue
            mx = (await s.execute(select(func.max(Tier.cashback)).where(Tier.offer_id.in_([o.id for o in os_])))).scalar() or 0
            b.button(text=f"{bk.emoji} {bk.name} · до {mx} ₽", callback_data=f"bank:{bk.id}")
        b.adjust(1)
    if not b.buttons: return await m.answer("Пока нет доступных предложений в этом разделе 🙏")
    head = {"cards": "💳 <b>Карты</b> — один банк, одна заявка", "bk": "⚽ <b>Ставки</b> · 18+/21+\nДепозит только своими деньгами",
            "mfo": "🏦 <b>Займы</b>", "cpl": "📝 <b>Заявки</b>"}[cat]
    await m.answer(head, reply_markup=b.as_markup())

@r.message(F.text == "💳 Карты")
async def c_cards(m: Message): await banks_view(m, "cards")

@r.message(F.text.in_({"⚽ Ставки", "🏦 Займы", "📝 Заявки"}))
async def c_gated(m: Message):
    cat = {"⚽ Ставки": "bk", "🏦 Займы": "mfo", "📝 Заявки": "cpl"}[m.text]
    title, on, gate = GATES[cat]
    if not on: return await m.answer(f"{title} — раздел на согласовании. Откроется позже.")
    if gate: return await m.answer(gate, reply_markup=ik([("Я понимаю, продолжить", f"gate:{cat}")]))
    await banks_view(m, cat)

@r.callback_query(F.data.startswith("gate:"))
async def gate_ok(c: CallbackQuery):
    await c.message.delete(); await banks_view(c.message, c.data.split(":")[1]); await c.answer()

@r.callback_query(F.data.startswith("bank:"))
async def bank_offers(c: CallbackQuery):
    bid = int(c.data.split(":")[1])
    async with Session() as s:
        bk = await s.get(Bank, bid)
        os_ = (await s.execute(select(Offer).where(Offer.bank_id == bid, Offer.enabled == True).order_by(Offer.sort))).scalars().all()
        
        b = InlineKeyboardBuilder()
        for o in os_:
            mx = (await s.execute(select(func.max(Tier.cashback)).where(Tier.offer_id == o.id))).scalar() or 0
            if bk.category == "cards": tag = "без покупки" if o.purchase_min == 0 else f"покупка от {o.purchase_min} ₽"
            elif bk.category == "bk": tag = "регистрация + депозит + ставка"
            elif bk.category == "mfo": tag = "условия займа"
            else: tag = "заявка / целевое действие"
            b.button(text=f"{o.name} · {mx} ₽ · {tag}", callback_data=f"offer:{o.id}")
        b.adjust(1); b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{bk.category}"))
    await c.message.edit_text(f"{bk.emoji} <b>{bk.name}</b>\n⚠️ Только <b>одно</b> предложение этого банка.", reply_markup=b.as_markup())
    await c.answer()

@r.callback_query(F.data.startswith("cat:"))
async def back_cat(c: CallbackQuery):
    await c.message.delete(); await banks_view(c.message, c.data.split(":")[1]); await c.answer()

@r.callback_query(F.data.startswith("offer:"))
async def offer_view(c: CallbackQuery):
    oid = int(c.data.split(":")[1])
    async with Session() as s:
        o = await s.get(Offer, oid); bk = await s.get(Bank, o.bank_id)
        ts = (await s.execute(select(Tier).where(Tier.offer_id == oid).order_by(Tier.payout.desc()))).scalars().all()
        txt = card(o, ts, bk)
    image_path = Path(o.image_path) if o.image_path and Path(o.image_path).exists() else Path("assets/offers") / bk.category / f"{o.code}.jpg"
    if bk.category == "bk" and not image_path.exists():
        bk_images = {"pari":"bk_green.jpg", "marathon":"bk_blue.jpg", "fonbet":"bk_orange.jpg", "melbet":"bk_red.jpg", "baltbet":"bk_gold.jpg", "leon":"bk_purple.jpg"}
        candidate = Path("assets/offers/bk") / bk_images.get(bk.slug, "bk_blue.jpg")
        if candidate.exists(): image_path = candidate
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Взять в работу", callback_data=f"take:{oid}")
    if o.source_url: kb.button(text="📃 Официальные правила", url=o.source_url)
    kb.button(text="⬅️ Назад", callback_data=f"bank:{o.bank_id}")
    kb.adjust(1)
    markup = kb.as_markup()
    if image_path.exists():
        await c.message.answer_photo(FSInputFile(image_path), caption=f"{bk.emoji} {bk.name} · {o.name}")
        await c.message.answer(txt, reply_markup=markup, disable_web_page_preview=True)
    else:
        await c.message.answer(txt, reply_markup=markup, disable_web_page_preview=True)
    await c.answer()

@r.message(St.age)
async def age_input(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    if not raw.isdigit() or not 18 <= int(raw) <= 120:
        return await m.answer("Введи полный возраст числом от 18 до 120 лет. Дату рождения присылать не нужно.")
    data = await state.get_data(); oid = data.get("oid")
    async with Session() as s:
        u = await s.get(User, m.from_user.id); o = await s.get(Offer, oid)
        if not o or not u: await state.clear(); return await m.answer("Оффер не найден.")
        years = int(raw)
        if not o.age_min <= years <= o.age_max:
            return await m.answer(f"Этот оффер доступен только в возрасте {o.age_min}–{o.age_max if o.age_max < 120 else 'без верхнего ограничения'} лет. Выбери другой оффер.")
        u.age_years = years; await s.commit()
    await state.clear()
    await m.answer("Возраст подходит. Продолжи оформление:", reply_markup=ik([("Продолжить оформление", f"take:{oid}")]))

@r.callback_query(F.data.startswith("take:"))
async def take(c: CallbackQuery, state: FSMContext, answer=True):
    oid = int(c.data.split(":")[1])
    async with Session() as s:
        u = (await s.execute(select(User).where(User.id == c.from_user.id).with_for_update())).scalar_one_or_none()
        o = await s.get(Offer, oid)
        if not u or not u.accepted or not u.adult: return await c.answer("Сначала подтверди возраст 18+ и правила через /start.", show_alert=True)
        if not o: return await c.answer("Предложение не найдено", show_alert=True)
        bk = await s.get(Bank, o.bank_id)
        if not bk or not o.enabled: return await c.answer("Предложение недоступно", show_alert=True)
        if o.age_min > 18 or o.age_max < 120:
            if u.age_years is None or not (o.age_min <= u.age_years <= o.age_max):
                await state.set_state(St.age); await state.update_data(oid=oid)
                await c.answer()
                await c.message.answer(f"Для этого предложения доступен возраст {o.age_min}–{o.age_max if o.age_max < 120 else 'без верхнего ограничения'} лет. Укажи число полных лет, без даты рождения.")
                return
        if bk.category == "bk" and o.network_status != "approved":
            return await c.answer("Букмекерский оффер ждёт письменного согласования кэшбэк-формата. Администратор должен отметить его как согласованный.", show_alert=True)
        if not o.url: return await c.answer("Партнёрская ссылка ещё не добавлена. Напиши в поддержку или выбери другой оффер.", show_alert=True)
        
        if await bank_taken(s, u.id, o.bank_id, u.phone_hash):
            return await c.answer("Ты уже брал предложение этого банка 🙌", show_alert=True)
        n = (await s.execute(select(func.count(App.id)).where(App.user_id == u.id,
             App.status.in_([NEW, PROOF, HOLD])))).scalar()
        if n >= cfg.max_active: return await c.answer(f"Максимум {cfg.max_active} активные заявки", show_alert=True)
        today = (await s.execute(select(func.count(App.id)).where(App.offer_id == oid,
             App.created >= datetime.utcnow().replace(hour=0, minute=0, second=0)))).scalar()
        if today >= o.slots: return await c.answer("Места на сегодня закончились 🙏", show_alert=True)
        tier = (await s.execute(select(Tier).where(Tier.offer_id == oid).order_by(Tier.id))).scalars().first()
        reward = int(tier.cashback) if tier else 0
        snapshot = {"code": o.code, "name": o.name, "brand": bk.name, "emoji": bk.emoji, "category": bk.category,
                    "condition": o.condition_text or o.action, "promo_notes": o.notes or "", "source_url": o.source_url or "",
                    "verification_steps": list(o.verification_steps or []), "proofs": list(o.required_proofs or []),
                    "reward": reward, "hold_days": o.hold, "age_min": o.age_min, "age_max": o.age_max,
                    "url": o.url, "link_param": o.link_param, "created_terms_at": datetime.utcnow().isoformat()}
        # subid is unique in DB; do not insert multiple rows with the same empty string.
        a = App(user_id=u.id, offer_id=oid, subid="pending-" + uuid.uuid4().hex,
                phone_hash=u.phone_hash, offer_snapshot=snapshot, cashback=0, payout=0)
        s.add(a); await s.commit()
        a.subid = subid(a.id)
        s.add(DealEvent(app_id=a.id, actor_id=u.id, event="created", from_status="", to_status=NEW, comment="Пользователь начал оформление"))
        await s.commit()
        url = link(o.url, a.subid, o.link_param); age = o.age_min
    dl = datetime.utcnow() + timedelta(hours=cfg.booking_h)
    await c.message.answer(
        f"🚀 <b>Заявка #{a.id} открыта</b>\n\n🔗 Твоя ссылка:\n{url or '⚠️ ссылка не задана — напиши в поддержку'}\n\n"
        f"🎯 {o.action}\n🔞 " + (f"{o.age_min}–{o.age_max} лет" if o.age_max < 120 else f"{o.age_min}+ лет") + f"\n💵 Вознаграждение: {reward} ₽ после проверки" + f"\n⏳ Холд: до {o.hold} дней после подтверждения сети\n⏳ Бронь до {dl:%d.%m %H:%M} UTC\n\n"
        f"❗️ Оформляй <b>только по этой ссылке</b>, не через приложение банка.\nВыполнил — жми «📤 Загрузить скрин».",
        reply_markup=ik([("📤 Загрузить скрин", f"proof:{a.id}")], [("📋 Мои заявки", "myapps")]),
        disable_web_page_preview=True)
    if answer: await c.answer()

@r.message(F.text == "📋 Мои заявки")
async def apps_m(m: Message): await apps_view(m)
@r.callback_query(F.data == "myapps")
async def apps_c(c: CallbackQuery): await apps_view(c.message); await c.answer()

async def apps_view(m: Message):
    async with Session() as s:
        apps = (await s.execute(select(App).where(App.user_id == m.chat.id).order_by(App.id.desc()).limit(20))).scalars().all()
        if not apps: return await m.answer("Заявок пока нет. Жми 💳 Карты")
        b = InlineKeyboardBuilder()
        for a in apps:
            o = await s.get(Offer, a.offer_id); bk = await s.get(Bank, o.bank_id)
            b.button(text=f"#{a.id} {bk.name} · {RU[a.status]}", callback_data=f"app:{a.id}")
        b.adjust(1)
    await m.answer("📋 <b>Мои заявки</b>", reply_markup=b.as_markup())

@r.callback_query(F.data.startswith("app:"))
async def app_view(c: CallbackQuery):
    aid = int(c.data.split(":")[1])
    async with Session() as s:
        a = await s.get(App, aid)
        if not a or a.user_id != c.from_user.id: return await c.answer("Не найдено", show_alert=True)
        o = await s.get(Offer, a.offer_id); bk = await s.get(Bank, o.bank_id)
        snap = a.offer_snapshot or {}
        reward = snap.get("reward", a.cashback or 0)
        t = f"📋 <b>Сделка #{a.id}</b>\n{bk.emoji} {bk.name} · {snap.get('name', o.name)}\n{'—'*22}\nСтатус: <b>{RU.get(a.status, a.status)}</b>\n🎯 {snap.get('condition', o.condition_text or o.action)}\n💰 Вознаграждение: {reward} ₽\n⏳ Холд: {snap.get('hold_days', o.hold)} дней после подтверждения сети\n"
        if a.status == NEW:
            frozen_url = snap.get("url", o.url)
            frozen_param = snap.get("link_param", o.link_param)
            t += f"⏳ Бронь до {(a.created + timedelta(hours=cfg.booking_h)):%d.%m %H:%M} UTC\n🔗 {link(frozen_url, a.subid, frozen_param)}"
        elif a.status == HOLD and a.hold_until:
            if a.hold_alerted_at or a.hold_until <= datetime.utcnow():
                t += f"⏳ Срок холда до {a.hold_until:%d.%m.%Y} завершился. Сейчас сделка проходит финальную ручную проверку; начисление появится после решения администратора."
            else:
                t += f"⏳ Подтверждение до <b>{a.hold_until:%d.%m.%Y}</b> (осталось {max(0,(a.hold_until-datetime.utcnow()).days)} дн.)"
        elif a.status in (CONFIRMED, PAID): t += f"💵 Начислено: <b>{a.cashback} ₽</b>"
        elif a.status == REJECTED: t += f"Причина: {a.reason or 'условие не выполнено'}"
        if snap.get("promo_notes"):
            t += "\n\n<b>Особые условия акции на момент оформления:</b>\n" + snap["promo_notes"]
        if snap.get("source_url"):
            t += "\nПравила: " + snap["source_url"]
        events = (await s.execute(select(DealEvent).where(DealEvent.app_id == a.id).order_by(DealEvent.created.desc()).limit(8))).scalars().all()
        if events:
            t += "\n\n<b>История:</b>\n" + "\n".join(f"{e.created:%d.%m %H:%M} · {e.comment or e.event}" for e in reversed(events))
        rows = [[("📤 Дослать подтверждения", f"proof:{a.id}")]] if a.status in (NEW, PROOF, HOLD) else []
        rows.append([("🆘 Вопрос по этой сделке", f"supapp:{a.id}")])
    await c.message.edit_text(t, reply_markup=ik(*rows), disable_web_page_preview=True); await c.answer()

@r.callback_query(F.data.startswith("proof:"))
async def proof_start(c: CallbackQuery, state: FSMContext):
    aid = int(c.data.split(":")[1])
    async with Session() as s:
        a = await s.get(App, aid); o = await s.get(Offer, a.offer_id) if a else None
        if not a or a.user_id != c.from_user.id or a.status not in (NEW, PROOF, HOLD):
            return await c.answer("Для этой сделки загрузка подтверждений закрыта", show_alert=True)
        required, received, missing = proof_progress(a, o)
        verification = a.verification or {}
        requested = verification.get("more_info_text") if verification.get("more_info_requested_at") else ""
        next_index = missing[0] if missing else len(required)
    await state.set_state(St.proof)
    await state.update_data(aid=aid)
    if missing:
        prompt = (f"📸 <b>Подтверждения по сделке #{aid}</b>\n\n"
                  f"Сейчас нужен пункт {next_index+1} из {len(required)}:\n<b>{required[next_index]}</b>")
    elif requested:
        prompt = (f"📸 <b>Дополнительное подтверждение по сделке #{aid}</b>\n\n"
                  f"Администратор запросил:\n{requested}\n\n"
                  "Отправь новый скриншот/документ, которого ещё нет в сделке.")
    else:
        prompt = f"По сделке #{aid} обязательные пункты уже загружены. Можно приложить дополнительные файлы или нажать «Отправить на проверку»."
    prompt += ("\n\nФИО оставь видимым только там, где это прямо указано в пункте проверки. "
               "Скрывай паспорт, дату рождения, адрес, телефон, полный номер карты/счёта, CVV/CVC, PIN, пароли, "
               "SMS-коды, QR-коды и лишние операции. Не присылай фото карты целиком, паспорт или договор займа.")
    await c.message.answer(prompt, reply_markup=ik([("✅ Отправить на проверку", f"proofdone:{aid}")], [("⬅️ К сделке", f"app:{aid}")]))
    await c.answer()

@r.message(St.proof, F.photo | F.document)
async def proof_got(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data(); aid = int(d.get("aid", 0))
    if m.document:
        allowed_mime = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
        if m.document.mime_type not in allowed_mime:
            return await m.answer("Пришли фото или PDF. Другие типы файлов не принимаются.")
        if m.document.file_size and m.document.file_size > 15 * 1024 * 1024:
            return await m.answer("Файл слишком большой. Максимальный размер — 15 МБ.")
    fid = m.photo[-1].file_id if m.photo else m.document.file_id
    should_hash = bool(m.photo) or bool(m.document and m.document.mime_type in {"image/jpeg", "image/png", "image/webp"})
    ph = None
    duplicate_suspected = False
    duplicate_matches = 0
    if should_hash:
        try:
            f = await bot.get_file(fid); buf = BytesIO(); await bot.download_file(f.file_path, destination=buf)
            ph = str(imagehash.phash(Image.open(BytesIO(buf.getvalue())).convert("RGB")))
        except Exception:
            ph = None
    async with Session() as s:
        a = (await s.execute(select(App).where(App.id == aid).with_for_update())).scalar_one_or_none()
        if not a or a.user_id != m.from_user.id or a.status not in (NEW, PROOF, HOLD):
            await state.clear(); return await m.answer("Сделка не найдена или уже закрыта.")
        o = await s.get(Offer, a.offer_id)
        required, received, missing = proof_progress(a, o)
        if ph:
            exact, duplicate_suspected, duplicate_matches = await services.phash_duplicates(s, ph, a.offer_id)
            if exact:
                return await m.answer("Этот документ уже загружали на данный оффер с другого аккаунта. Нужен оригинальный документ именно для вашей заявки.")
        current_index = missing[0] if missing else None
        label = required[current_index] if current_index is not None else "Дополнительное подтверждение"
        old_status = a.status
        proof_item = {
            "file_id": fid, "kind": "photo" if m.photo else "document",
            "name": (m.document.file_name if m.document else "") or "",
            "hash": ph, "proof_index": current_index, "label": label,
            "duplicate_suspected": duplicate_suspected, "duplicate_matches": duplicate_matches,
            "uploaded_at": datetime.utcnow().isoformat()
        }
        if ph:
            services.add_proof_fingerprint(s, offer_id=a.offer_id, app_id=a.id, user_id=m.from_user.id, ph=ph)
            try:
                await s.flush()
            except IntegrityError:
                await s.rollback()
                return await m.answer("Этот документ уже загружали на данный оффер с другого аккаунта. Нужен оригинальный документ именно для вашей заявки.")
        a.proof = fid; a.proof_hash = ph
        a.proof_files = list(a.proof_files or []) + [proof_item]
        if a.status == NEW:
            a.status = PROOF
        ver = dict(a.verification or {})
        ver.pop("proof_submitted_at", None)
        ver["proof_last_received_at"] = proof_item["uploaded_at"]
        a.verification = ver
        s.add(DealEvent(app_id=a.id, actor_id=m.from_user.id, event="proof_uploaded",
                        from_status=old_status, to_status=a.status, comment=f"Загружено: {label}"))
        await s.commit()
        required, received, missing = proof_progress(a, o)
        if missing:
            next_text = f"Следующий пункт {missing[0]+1} из {len(required)}:\n<b>{required[missing[0]]}</b>"
        else:
            next_text = "Все обязательные пункты загружены. Нажми «Отправить на проверку» или приложи дополнительные материалы."
    duplicate_note = ("\n⚠️ Похожий скрин найден в других материалах. Файл сохранён, администратор дополнительно сверит его вручную." if duplicate_suspected else "")
    await m.answer(f"✅ Файл добавлен к сделке #{aid}.\nПункт: {label}{duplicate_note}\n\n{next_text}",
                    reply_markup=ik([("✅ Отправить на проверку", f"proofdone:{aid}")], [("📎 Добавить ещё файл", f"proof:{aid}")]))

@r.callback_query(F.data.startswith("proofdone:"))
async def proof_done(c: CallbackQuery, state: FSMContext, bot: Bot):
    aid = int(c.data.split(":")[1])
    async with Session() as s:
        a = (await s.execute(select(App).where(App.id == aid).with_for_update())).scalar_one_or_none()
        if not a or a.user_id != c.from_user.id or a.status not in (PROOF, HOLD):
            return await c.answer("Сделка не найдена или пока не содержит подтверждений.", show_alert=True)
        o = await s.get(Offer, a.offer_id)
        complete, missing_labels = proofs_complete(a, o, require_submission=False)
        if not complete:
            return await c.answer("Не хватает подтверждений: " + "; ".join(missing_labels[:2]), show_alert=True)
        ver = dict(a.verification or {})
        submitted_at = ver.get("proof_submitted_at")
        last_received = ver.get("proof_last_received_at")
        if submitted_at and (not last_received or last_received <= submitted_at):
            return await c.answer("Этот комплект уже отправлен на проверку. Дождись решения администратора.", show_alert=True)
        old = a.status
        ver["proof_submitted_at"] = datetime.utcnow().isoformat()
        ver.pop("more_info_requested_at", None); ver.pop("more_info_text", None)
        a.verification = ver
        s.add(DealEvent(app_id=a.id, actor_id=c.from_user.id, event="proof_submitted",
                        from_status=old, to_status=a.status, comment="Пользователь отправил полный комплект на проверку"))
        o_name = (a.offer_snapshot or {}).get("name", o.name)
        file_count = len(a.proof_files or [])
        user_id = a.user_id
        deal_status = RU.get(a.status, a.status)
        await s.commit()
        keyboard = ik([("🔎 Открыть сделку", f"adm:deal:{aid}"), ("📎 Все доказательства", f"adm:proofs:{aid}")],
                      [("✅ Начислить сейчас", f"adm:confirm:{aid}"), ("⏳ В холд", f"adm:hold:{aid}")],
                      [("📝 Запросить ещё данные", f"adm:more:{aid}"), ("❌ Отказ с причиной", f"adm:no:{aid}")])
        for ad in cfg.admins:
            await notify(bot, ad, f"📥 <b>Комплект доказательств отправлен</b>\nСделка #{aid} · {o_name}\n"
                         f"Пользователь: @{c.from_user.username or 'без username'} · ID {user_id}\n"
                         f"Файлов: {file_count}\nСтатус сделки: {deal_status}", reply_markup=keyboard)
    await state.clear()
    await c.message.answer(f"✅ Полный комплект по сделке #{aid} отправлен на рассмотрение. Мы уведомили администратора.")
    await c.answer("Отправлено на проверку")

@r.message(F.text == "💰 Кошелёк")
async def wallet(m: Message):
    async with Session() as s:
        u = await s.get(User, m.from_user.id)
        apps = (await s.execute(select(App).where(App.user_id == u.id))).scalars().all()
        reward_of = lambda a: int((a.offer_snapshot or {}).get("reward", 0))
        pending_setup = sum(reward_of(a) for a in apps if a.status == NEW)
        review = sum(reward_of(a) for a in apps if a.status == PROOF)
        hold = sum(reward_of(a) for a in apps if a.status == HOLD)
        reserved = (await s.execute(select(func.coalesce(func.sum(PayoutReq.amount),0)).where(PayoutReq.user_id==u.id, PayoutReq.status.in_(["pending","processing","review_required"])))).scalar()
        paid = (await s.execute(select(func.coalesce(func.sum(PayoutReq.amount),0)).where(PayoutReq.user_id==u.id, PayoutReq.status=="paid"))).scalar()
        referral_commission = (await s.execute(select(func.coalesce(func.sum(RefAcc.amount), 0)).where(RefAcc.referrer_id == u.id))).scalar() or 0
        first_payout_bonuses = (await s.execute(select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
            WalletEntry.user_id == u.id, WalletEntry.kind == "task_ref_bonus"))).scalar() or 0
        refs = int(referral_commission) + int(first_payout_bonuses)
    await m.answer(f"💰 <b>Мой кошелёк</b>\n{'—'*22}\n📝 Оформляются: <b>{pending_setup} ₽</b>\n🟡 На рассмотрении: <b>{review} ₽</b>\n⏳ В холде: <b>{hold} ₽</b>\n🟢 Доступно к выводу: <b>{u.balance} ₽</b>\n🔵 Зарезервировано под вывод: <b>{reserved} ₽</b>\n✅ Уже выплачено: <b>{paid} ₽</b>\n👥 Начисления с друзей: {refs} ₽\n\nМинимальный вывод: {cfg.min_wd} ₽ по СБП.",
                    reply_markup=ik([("💸 Запросить вывод", "wd")], [("📜 История сделок и выплат", "hist")], [("⚙️ Реквизиты и настройки", "settings")]))

@r.callback_query(F.data == "hist")
async def hist(c: CallbackQuery):
    async with Session() as s:
        apps = (await s.execute(select(App).where(App.user_id == c.from_user.id).order_by(App.id.desc()).limit(10))).scalars().all()
        ps = (await s.execute(select(PayoutReq).where(PayoutReq.user_id == c.from_user.id).order_by(PayoutReq.id.desc()).limit(10))).scalars().all()
        payout_events = {}
        for p in ps:
            payout_events[p.id] = (await s.execute(select(PayoutEvent).where(PayoutEvent.payout_id == p.id).order_by(PayoutEvent.created.desc()).limit(5))).scalars().all()
    lines = [f"Сделка #{a.id} · {(a.offer_snapshot or {}).get('name','Оффер')} · {RU.get(a.status,a.status)} · {(a.offer_snapshot or {}).get('reward',a.cashback)} ₽ · {a.created:%d.%m.%Y}" for a in apps]
    payout_ru = {"pending":"ожидает проверки", "processing":"в обработке", "review_required":"нужна сверка после отзыва лида", "paid":"выплачено", "rejected":"отклонено", "cancelled":"отменено"}
    for p in ps:
        timeline = " → ".join(f"{ev.created:%d.%m %H:%M}: {ev.comment or ev.event}" for ev in reversed(payout_events[p.id]))
        lines.append(f"Вывод #{p.id} · {p.amount} ₽ · {payout_ru.get(p.status,p.status)} · создан {p.created:%d.%m.%Y}" +
                     (f" · выплачен {p.paid_at:%d.%m.%Y}" if p.paid_at else "") +
                     (f" · {p.admin_note}" if p.admin_note else "") + (f"\n  История: {timeline}" if timeline else ""))
    await c.message.answer("📜 <b>История операций</b>\n" + ("\n".join(lines) if lines else "Пока пусто"))
    for p in ps:
        if p.status == "pending":
            await c.message.answer(f"Запрос на вывод #{p.id} ещё не взят в работу.", reply_markup=ik([("Отменить запрос", f"wdcancel:{p.id}")]))
    await c.answer()

@r.callback_query(F.data.startswith("wdcancel:"))
async def wd_cancel(c: CallbackQuery, bot: Bot):
    pid = int(c.data.split(":")[1])
    async with Session() as s:
        pre = await s.get(PayoutReq, pid)
        if not pre or pre.user_id != c.from_user.id:
            return await c.answer("Запрос на вывод не найден.", show_alert=True)
        u = (await s.execute(select(User).where(User.id == c.from_user.id).with_for_update())).scalar_one_or_none()
        p = (await s.execute(select(PayoutReq).where(PayoutReq.id == pid).with_for_update())).scalar_one_or_none()
        if not u or not p or p.user_id != c.from_user.id or p.status != "pending":
            return await c.answer("Отменить можно только запрос, который ещё не взят в работу.", show_alert=True)
        old = p.status; p.status, p.updated_at = "cancelled", datetime.utcnow()
        ref = f"withdraw-cancel:{p.id}"
        exists = (await s.execute(select(WalletEntry).where(WalletEntry.ref == ref))).scalar_one_or_none()
        if not exists:
            u.balance += p.amount
            s.add(WalletEntry(user_id=u.id, amount=p.amount, kind="withdraw_cancel", ref=ref, note="Возврат пользователю отменённого запроса"))
        s.add(PayoutEvent(payout_id=p.id, actor_id=u.id, event="cancelled", from_status=old, to_status="cancelled", comment="Пользователь отменил запрос до взятия в работу"))
        await s.commit()
        for ad in cfg.admins: await notify(bot, ad, f"Запрос на вывод #{p.id} отменён пользователем; {p.amount} ₽ возвращены на баланс.")
    await c.answer("Запрос отменён, деньги возвращены на доступный баланс.", show_alert=True)

@r.message(F.text == "⚙️ Настройки")
async def settings_message(m: Message):
    async with Session() as s:
        u = await s.get(User, m.from_user.id)
        stored = phone_decrypt(u.sbp_phone) if u.sbp_phone else "не указан"
        masked = f"+7 *** ***-{stored[-4:]}" if stored != "не указан" else stored
        bank = u.sbp_bank or "не выбран"
    await m.answer(f"⚙️ <b>Настройки выплат</b>\nБанк СБП: <b>{bank}</b>\nТелефон: <b>{masked}</b>\n\nРеквизиты зашифрованы и копируются в каждый запрос на вывод.",
        reply_markup=ik([("🏦 Изменить банк", "settings:bank")], [("📱 Изменить телефон", "settings:phone")], [("💰 К кошельку", "wallet")]))

@r.callback_query(F.data == "wallet")
async def wallet_callback(c: CallbackQuery):
    await c.message.answer("Открой раздел 💰 Кошелёк в меню, чтобы увидеть все балансы.")
    await c.answer()

@r.callback_query(F.data == "settings")
async def settings(c: CallbackQuery):
    async with Session() as s:
        u = await s.get(User, c.from_user.id)
        stored = phone_decrypt(u.sbp_phone) if u.sbp_phone else "не указан"
        masked = f"+7 *** ***-{stored[-4:]}" if stored != "не указан" else stored
        bank = u.sbp_bank or "не выбран"
    await c.message.answer(f"⚙️ <b>Настройки выплат</b>\nБанк СБП: <b>{bank}</b>\nТелефон: <b>{masked}</b>\n\nРеквизиты зашифрованы. При создании вывода копируются в заявку и не меняются задним числом.",
        reply_markup=ik([("🏦 Изменить банк", "settings:bank")], [("📱 Изменить телефон", "settings:phone")], [("⬅️ К кошельку", "wallet")]))

@r.callback_query(F.data == "settings:bank")
async def settings_bank(c: CallbackQuery, state: FSMContext):
    await state.set_state(St.sbp_bank); await c.message.answer("Напиши название банка для СБП (например, Т-Банк, Сбербанк, ВТБ).") ; await c.answer()

@r.message(St.sbp_bank)
async def settings_bank_save(m: Message, state: FSMContext):
    bank = (m.text or "").strip()
    if len(bank) < 2 or len(bank) > 80: return await m.answer("Укажи корректное название банка.")
    async with Session() as s:
        u = await s.get(User, m.from_user.id); u.sbp_bank = bank; await s.commit()
    await state.clear(); await m.answer("Банк для СБП сохранён.")

@r.callback_query(F.data == "settings:phone")
async def settings_phone(c: CallbackQuery, state: FSMContext):
    await state.set_state(St.sbp_phone); await c.message.answer("Введи телефон для СБП в формате +79991234567. Не присылай номер карты.") ; await c.answer()

@r.message(St.sbp_phone)
async def settings_phone_save(m: Message, state: FSMContext):
    ph = phone_norm(m.text)
    if len(ph) != 11: return await m.answer("Нужен номер телефона из 11 цифр.")
    async with Session() as s:
        u = await s.get(User, m.from_user.id); u.sbp_phone = phone_encrypt(ph); u.phone_hash = phash(ph); await s.commit()
    await state.clear(); await m.answer("Телефон СБП сохранён в зашифрованном виде.")

@r.callback_query(F.data.startswith("supapp:"))
async def sup_app(c: CallbackQuery, state: FSMContext):
    aid = int(c.data.split(":")[1])
    async with Session() as s:
        a = await s.get(App, aid)
        if not a or a.user_id != c.from_user.id: return await c.answer("Сделка не найдена", show_alert=True)
    await state.set_state(St.sup); await state.update_data(app_id=aid)
    await c.message.answer(f"Опиши вопрос по сделке #{aid}. Сообщение увидит поддержка."); await c.answer()

@r.callback_query(F.data == "wd")
async def wd(c: CallbackQuery, state: FSMContext):
    async with Session() as s: u = await s.get(User, c.from_user.id)
    if not u.sbp_bank or not u.sbp_phone:
        return await c.answer("Сначала заполни банк и телефон в настройках реквизитов.", show_alert=True)
    if u.balance < cfg.min_wd: return await c.answer(f"Минимум {cfg.min_wd} ₽, доступно {u.balance} ₽", show_alert=True)
    await state.set_state(St.wd_amt); await state.update_data(mx=u.balance)
    await c.message.answer(f"Сколько вывести? Укажи сумму от {cfg.min_wd} до {u.balance} ₽.")
    await c.answer()

@r.message(St.wd_amt)
async def wd_amt(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data(); raw = (m.text or "").strip()
    if not raw.isdigit() or not cfg.min_wd <= int(raw) <= d.get("mx",0):
        return await m.answer(f"Введи целое число от {cfg.min_wd} до {d.get('mx',0)} ₽.")
    amount = int(raw)
    async with Session() as s:
        u = (await s.execute(select(User).where(User.id == m.from_user.id).with_for_update())).scalar_one_or_none()
        if not u or u.balance < amount: await state.clear(); return await m.answer("Недостаточно доступных средств. Обнови кошелёк.")
        if not u.sbp_bank or not u.sbp_phone: await state.clear(); return await m.answer("Сначала заполни реквизиты в настройках.")
        u.balance -= amount
        p = PayoutReq(user_id=u.id, amount=amount, phone=u.sbp_phone, bank=u.sbp_bank, status="pending")
        s.add(p); await s.flush()
        s.add(WalletEntry(user_id=u.id, amount=-amount, kind="withdraw_request", ref=f"withdraw:{p.id}", note="Резерв под запрос на вывод"))
        s.add(PayoutEvent(payout_id=p.id, actor_id=u.id, event="created", from_status="", to_status="pending", comment="Пользователь создал запрос на вывод"))
        await s.commit()
        phone = phone_decrypt(p.phone)
        for ad in cfg.admins:
            await notify(bot, ad, f"💸 <b>Новый запрос на вывод #{p.id}</b>\nСумма: {amount} ₽\nБанк: {p.bank}\nТелефон СБП: {phone}\nПользователь: {u.id} (@{u.username or 'без username'})")
    await state.clear()
    await m.answer(f"✅ Запрос на вывод #{p.id} создан. {amount} ₽ зарезервированы до решения администратора. Статус появится в истории выплат.")

@r.message(F.text == "👥 Друзья")
async def friends(m: Message, bot: Bot):
    me = await bot.get_me()
    async with Session() as s:
        u = await s.get(User, m.from_user.id)
        cnt = (await s.execute(select(func.count(User.id)).where(User.referrer_id == u.id))).scalar()
        act = (await s.execute(select(func.count(func.distinct(App.user_id))).join(User, User.id == App.user_id)
               .where(User.referrer_id == u.id, App.status.in_([CONFIRMED, PAID])))).scalar()
        referral_commission = (await s.execute(select(func.coalesce(func.sum(RefAcc.amount), 0)).where(RefAcc.referrer_id == u.id))).scalar() or 0
        first_payout_bonuses = (await s.execute(select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
            WalletEntry.user_id == u.id, WalletEntry.kind == "task_ref_bonus"))).scalar() or 0
        earn = int(referral_commission) + int(first_payout_bonuses)
    url = f"https://t.me/{me.username}?start=ref_{u.id}"
    share = f"https://t.me/share/url?url={url}&text=Кэшбэк за оформление банковской карты"
    await m.answer(f"👥 <b>Приглашай друзей</b>\n\n🔗 {url}\n\nПриглашено: {cnt} · Активных: {act}\n"
                   f"Заработано: <b>{earn} ₽</b>\n\nТы получаешь <b>{cfg.ref_pct}%</b> с каждой выплаты друга. "
                   f"Друг получает столько же, сколько все — ему ничего не урезается.",
                 reply_markup=ik_url("📤 Поделиться", share), disable_web_page_preview=True)

@r.message(Command("support"))
async def support_cmd(m: Message, state: FSMContext):
    await state.set_state(St.sup)
    await m.answer("Опиши вопрос одним сообщением — ответим здесь.")


@r.message(F.text == "🆘 Поддержка")
async def sup(m: Message, state: FSMContext):
    await state.set_state(St.sup); await m.answer("Опиши вопрос одним сообщением — ответим здесь.")
@r.callback_query(F.data == "sup")
async def sup_c(c: CallbackQuery, state: FSMContext):
    await state.set_state(St.sup); await c.message.answer("Опиши вопрос одним сообщением."); await c.answer()
@r.message(St.sup)
async def sup_got(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data(); await state.clear()
    app_id = data.get("app_id")
    for ad in cfg.admins: await notify(bot, ad, f"🆘 Обращение от @{m.from_user.username} (id {m.from_user.id})" + (f" по сделке #{app_id}" if app_id else "") + f":\n{m.text}")
    await m.answer("Сообщение отправлено в поддержку. Ответ придёт сюда.")

@r.message(F.text == "/how")
async def how(m: Message): await m.answer(HOW)

START_PITCH = (
    "🏆 <b>BONVERA</b> — кэшбэк за то, что ты и так оформляешь\n\n"
    "💳 Карты · ⚽ Букмекеры · 🏦 Займы · 📝 Заявки\n"
    "💸 Вознаграждение до 3 640 ₽ за одно предложение\n\n"
    "<b>Как это работает</b>\n"
    "1️⃣ Выбираешь предложение в приложении\n"
    "2️⃣ Оформляешь по нашей ссылке\n"
    "3️⃣ Загружаешь подтверждение\n"
    "4️⃣ Получаешь деньги на кошелёк\n\n"
    "⏳ Выплата после подтверждения партнёра: 14–60 дней\n"
    "💳 Покупки и депозиты — твоими деньгами. Мы не даём денег на оформление и не просим вложений"
)

STATUS_RU = {"new": "Новая", "proof": "На проверке", "hold": "Холд", "confirmed": "Подтверждена",
             "paid": "Выплачена", "rejected": "Отклонена", "expired": "Истекла"}


def start_kb(uid: int):
    """Regular users get one call to action; admins also get the panel button."""
    rows = []
    if cfg.webapp_url:
        rows.append([InlineKeyboardButton(text="📱 Открыть BONVERA", web_app=WebAppInfo(url=cfg.webapp_url))])
    if uid in cfg.admins:
        rows.append([InlineKeyboardButton(text="🛠 Админ-меню", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


HELP_TEXT = (START_PITCH +
    "\n\n<b>Где смотреть статус</b>\n"
    "• 📋 Мои заявки — статус, срок брони и загруженные доказательства\n"
    "• /deals — последние 5 заявок одной строкой\n"
    "• /balance — кошелёк: доступно, в проверке, в холде\n\n"
    "<b>Когда и сколько платят</b>\n"
    "• Сумма закреплена в карточке оффера и не меняется после оформления\n"
    "• Зачисление на кошелёк — после подтверждения партнёра, холд оффера указан в карточке\n"
    f"• Вывод от {cfg.min_wd} ₽ по СБП, раздел «💰 Кошелёк»\n\n"
    "<b>Поддержка</b>\n"
    "• /support — опиши проблему одним сообщением, ответим в этом же чате\n"
    "• По конкретной сделке — кнопка «🆘 Вопрос по этой сделке» в её карточке")


@r.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer(HELP_TEXT, reply_markup=start_kb(m.from_user.id))


@r.callback_query(F.data == "howto")
async def howto_cb(c: CallbackQuery):
    await c.message.answer(HELP_TEXT, reply_markup=start_kb(c.from_user.id))
    await c.answer()


async def balance_text(uid: int) -> str:
    async with Session() as s:
        u = await s.get(User, uid)
        if not u:
            return "Сначала нажми /start"
        hold = int((await s.execute(select(func.coalesce(func.sum(App.cashback), 0)).where(
            App.user_id == uid, App.status.in_(["proof", "hold"])))).scalar() or 0)
        done = int((await s.execute(select(func.coalesce(func.sum(App.cashback), 0)).where(
            App.user_id == uid, App.status.in_(["confirmed", "paid"])))).scalar() or 0)
        refs = int((await s.execute(select(func.count(User.id)).where(User.referrer_id == uid))).scalar() or 0)
    return ("💰 <b>Кошелёк</b>\n\n"
            f"Доступно к выводу: <b>{int(u.balance or 0)} ₽</b>\n"
            f"В проверке и холде: {hold} ₽\n"
            f"Начислено за всё время: {done} ₽\n"
            f"Приглашено друзей: {refs}\n\n"
            "Вывод от 300 ₽ — в приложении, раздел «Кошелёк»")


@r.message(Command("balance"))
async def balance_cmd(m: Message):
    await m.answer(await balance_text(m.from_user.id), reply_markup=start_kb(m.from_user.id))


@r.callback_query(F.data == "quickbal")
async def quickbal_cb(c: CallbackQuery):
    await c.message.answer(await balance_text(c.from_user.id))
    await c.answer()


@r.message(Command("deals"))
async def deals_cmd(m: Message):
    async with Session() as s:
        rows = (await s.execute(select(App).where(App.user_id == m.from_user.id)
                                .order_by(App.created.desc()).limit(5))).scalars().all()
    if not rows:
        await m.answer("Заявок пока нет. Выбери предложение в приложении 👇", reply_markup=start_kb(m.from_user.id))
        return
    lines = []
    for a in rows:
        lines.append(f"#{a.id} · {STATUS_RU.get(a.status, a.status)} · {int(a.cashback or 0)} ₽")
    await m.answer("📋 <b>Последние заявки</b>\n\n" + "\n".join(lines) +
                   "\n\nПодробности и доказательства — в приложении.", reply_markup=start_kb(m.from_user.id))
