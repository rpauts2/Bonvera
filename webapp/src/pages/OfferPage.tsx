import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useLoad } from "../lib/useLoad";
import type { OfferDetail, TakeResult, UserProfile } from "../lib/types";
import { useSession } from "../state/session";
import { Icon } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader, SectionTitle } from "../components/ui";
import { haptic, hapticNotify, openExternal, showAlert } from "../lib/telegram";

const CAT_LABEL: Record<string, string> = {
  cards: "Банковская карта",
  bk: "Букмекер",
  mfo: "Займ МФО",
  cpl: "CPL-заявка",
};

export default function OfferPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, refresh } = useSession();
  const { data: offer, error, reload } = useLoad<OfferDetail>(`/offers/${id}`);
  const [taking, setTaking] = useState(false);
  const [needAge, setNeedAge] = useState(false);
  const [ageInput, setAgeInput] = useState("");
  const [ageSaving, setAgeSaving] = useState(false);

  async function take() {
    if (!offer) return;
    setTaking(true);
    haptic("medium");
    try {
      const res = await api.post<TakeResult>(`/offers/${offer.id}/take`);
      hapticNotify("success");
      navigate(`/apps/${res.app_id}`);
    } catch (e) {
      hapticNotify("error");
      if (e instanceof ApiError && e.code === "age_required") {
        setNeedAge(true);
      } else {
        showAlert(e instanceof Error ? e.message : "Не удалось создать заявку.");
      }
      void reload();
    } finally {
      setTaking(false);
    }
  }

  async function saveAgeAndTake() {
    const years = Number(ageInput);
    if (!Number.isInteger(years) || years < 18 || years > 120) {
      showAlert("Укажи число полных лет от 18 до 120.");
      return;
    }
    setAgeSaving(true);
    try {
      await api.put<UserProfile>("/me/age", { years });
      await refresh();
      setNeedAge(false);
      await take();
    } catch (e) {
      showAlert(e instanceof Error ? e.message : "Не удалось сохранить возраст.");
    } finally {
      setAgeSaving(false);
    }
  }

  const ageBlocked =
    offer && user?.age_years != null && (user.age_years < offer.age_min || user.age_years > offer.age_max);

  return (
    <div>
      <PageHeader title="Предложение" back="/catalog" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!offer && !error && <ListSkeleton rows={3} />}
      {offer && (
        <>
          <section className="px-5">
            <div className="card-glass overflow-hidden">
              <div className="relative h-44 w-full overflow-hidden bg-navy-800">
                <img
                  src={offer.image_url}
                  alt={`${offer.brand} · ${offer.name}`}
                  className="h-full w-full object-cover"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-navy-950 via-navy-950/20 to-transparent" />
                <span className="absolute left-4 top-4 rounded-full border border-royal/30 bg-navy-950/80 px-3 py-1 text-[12px] font-bold text-indigo-200 backdrop-blur">
                  {CAT_LABEL[offer.category] ?? offer.category}
                </span>
              </div>
              <div className="p-5">
                <div className="text-[12px] font-semibold uppercase tracking-wide text-indigo-300/75">
                  {offer.emoji} {offer.brand}
                </div>
                <h2 className="mt-1 text-lg font-extrabold leading-snug">{offer.name}</h2>
                <div className="mt-3 flex items-end justify-between">
                  <div>
                    <div className="text-3xl font-extrabold text-gold-gradient">
                      {offer.reward.toLocaleString("ru-RU")} ₽
                    </div>
                    <div className="text-[12px] text-indigo-300/70">награда за выполнение</div>
                  </div>
                  <div className="text-right text-[12px] text-indigo-300/75">
                    <div className="flex items-center justify-end gap-1">
                      <Icon name="clock" className="h-3.5 w-3.5" /> холд {offer.hold_days} дн.
                    </div>
                    {offer.purchase_min > 0 && <div className="mt-1">покупка от {offer.purchase_min} ₽</div>}
                    <div className="mt-1">
                      возраст {offer.age_min}–{offer.age_max}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {offer.category === "mfo" && (
            <section className="px-5 pt-3">
              <div className="rounded-3xl border border-rose-alert/35 bg-rose-alert/8 p-5">
                <div className="flex items-center gap-2 text-sm font-extrabold text-rose-alert">
                  <Icon name="shield" className="h-5 w-5" /> Займ — это долговое обязательство
                </div>
                <p className="mt-2 text-xs leading-relaxed text-indigo-200/75">
                  Микрозайм нужно вернуть в срок с процентами. Это не заработок и не инвестиция.
                  Оценивай свои возможности: просрочка ведёт к долгам и ухудшению кредитной истории.
                </p>
                {offer.mfo_info && (
                  <div className="mt-3 grid grid-cols-2 gap-2 text-[12px]">
                    {offer.mfo_info.psk && (
                      <div className="rounded-xl bg-navy-950/60 p-2.5">
                        <div className="text-indigo-300/70">ПСК</div>
                        <div className="font-bold text-indigo-100">{offer.mfo_info.psk}</div>
                      </div>
                    )}
                    {offer.mfo_info.rate && (
                      <div className="rounded-xl bg-navy-950/60 p-2.5">
                        <div className="text-indigo-300/70">Ставка</div>
                        <div className="font-bold text-indigo-100">{offer.mfo_info.rate}</div>
                      </div>
                    )}
                    {offer.mfo_info.term && (
                      <div className="rounded-xl bg-navy-950/60 p-2.5">
                        <div className="text-indigo-300/70">Срок</div>
                        <div className="font-bold text-indigo-100">{offer.mfo_info.term}</div>
                      </div>
                    )}
                    {offer.mfo_info.registry && (
                      <div className="rounded-xl bg-navy-950/60 p-2.5">
                        <div className="text-indigo-300/70">Реестр ЦБ</div>
                        <div className="font-bold text-indigo-100">{offer.mfo_info.registry}</div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </section>
          )}

          {offer.category === "bk" && (
            <section className="px-5 pt-3">
              <div className="rounded-3xl border border-gold/30 bg-gold/8 p-4 text-xs leading-relaxed text-indigo-200/75">
                <span className="font-bold text-gold">Ставки — это риск, а не заработок.</span> Бонус
                начисляется за выполненное условие партнёра, а не за выигрыш. Играй ответственно и только
                на суммы, которые не боишься потерять.
              </div>
            </section>
          )}

          <SectionTitle>Условие</SectionTitle>
          <section className="px-5">
            <div className="card-glass space-y-3 p-5 text-sm leading-relaxed text-indigo-200/80">
              <p className="font-bold text-indigo-100">{offer.condition}</p>
              {offer.action && <p className="whitespace-pre-line text-xs text-indigo-200/65">{offer.action}</p>}
              {offer.rules && <p className="whitespace-pre-line text-xs text-indigo-200/65">{offer.rules}</p>}
            </div>
          </section>

          {offer.verification_steps.length > 0 && (
            <>
              <SectionTitle>Как проходит проверка</SectionTitle>
              <section className="px-5">
                <div className="card-glass space-y-3 p-5">
                  {offer.verification_steps.map((s, i) => (
                    <div key={i} className="flex gap-3 text-xs leading-relaxed text-indigo-200/75">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-royal/20 text-[12px] font-bold text-royal-soft">
                        {i + 1}
                      </span>
                      <span className="pt-0.5">{s}</span>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}

          {offer.required_proofs.length > 0 && (
            <>
              <SectionTitle>Что понадобится для подтверждения</SectionTitle>
              <section className="flex flex-wrap gap-2 px-5">
                {offer.required_proofs.map((p, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1.5 rounded-full border border-electric/25 bg-electric/10 px-3 py-1.5 text-[12px] font-semibold text-electric"
                  >
                    <Icon name="camera" className="h-3.5 w-3.5" /> {p}
                  </span>
                ))}
              </section>
            </>
          )}

          {(offer.allowed.length > 0 || offer.forbidden.length > 0) && (
            <section className="mt-4 grid grid-cols-1 gap-3 px-5">
              {offer.allowed.length > 0 && (
                <div className="card-glass p-4">
                  <div className="mb-2 text-xs font-bold text-emerald-glow">Разрешено</div>
                  <ul className="space-y-1.5 text-xs text-indigo-200/70">
                    {offer.allowed.map((a, i) => (
                      <li key={i} className="flex gap-2">
                        <Icon name="check" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-glow" /> {a}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {offer.forbidden.length > 0 && (
                <div className="card-glass p-4">
                  <div className="mb-2 text-xs font-bold text-rose-alert">Запрещено</div>
                  <ul className="space-y-1.5 text-xs text-indigo-200/70">
                    {offer.forbidden.map((f, i) => (
                      <li key={i} className="flex gap-2">
                        <Icon name="cross" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-alert" /> {f}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          {offer.notes && (
            <section className="px-5 pt-4">
              <p className="whitespace-pre-line text-[12px] leading-relaxed text-indigo-300/70">{offer.notes}</p>
            </section>
          )}

          <section className="px-5 pb-8 pt-5">
            {offer.slots_left_today != null && offer.available && (
              <p className="mb-2 text-center text-[12px] text-indigo-300/75">
                Осталось мест сегодня: <span className="font-bold text-electric">{offer.slots_left_today}</span>
              </p>
            )}
            {needAge ? (
              <div className="card-glass space-y-3 p-5">
                <div className="text-sm font-extrabold text-indigo-100">
                  Подтверди возраст для этого предложения
                </div>
                <p className="text-[12px] leading-relaxed text-indigo-300/75">
                  Доступный возраст: {offer.age_min}–{offer.age_max} лет. Возраст проверяется на сервере
                  и сохраняется в профиле — вводить его повторно не потребуется.
                </p>
                <input
                  type="number"
                  inputMode="numeric"
                  min={18}
                  max={120}
                  className="input-dark w-full"
                  placeholder="Полных лет, например 25"
                  value={ageInput}
                  onChange={(e) => setAgeInput(e.target.value)}
                  aria-label="Число полных лет"
                />
                <button
                  className="btn-gold w-full"
                  disabled={ageSaving || taking}
                  onClick={() => void saveAgeAndTake()}
                >
                  <Icon name="check" className="h-4 w-4" />
                  {ageSaving || taking ? "Проверяю…" : "Подтвердить возраст и оформить"}
                </button>
                <button className="btn-ghost w-full text-xs" onClick={() => setNeedAge(false)}>
                  Отмена
                </button>
              </div>
            ) : offer.already_taken ? (
              <Link to="/apps" className="btn-primary w-full" onClick={() => haptic("light")}>
                <Icon name="doc" className="h-4 w-4" /> Заявка уже оформлена — открыть
              </Link>
            ) : offer.available && !ageBlocked ? (
              <button className="btn-gold w-full" disabled={taking} onClick={() => void take()}>
                <Icon name="spark" className="h-4 w-4" />
                {taking ? "Создаю заявку…" : "Оформить заявку"}
              </button>
            ) : (
              <div className="space-y-2">
                <button className="btn-gold w-full" disabled>
                  <Icon name="lock" className="h-4 w-4" /> Оформление недоступно
                </button>
                <p className="text-center text-[12px] leading-relaxed text-indigo-300/75">
                  {ageBlocked
                    ? `Предложение доступно для возраста ${offer.age_min}–${offer.age_max} лет.`
                    : offer.unavailable_reason ??
                      "Партнёрская ссылка ещё не добавлена или предложение временно недоступно."}
                </p>
              </div>
            )}
            {offer.source_url && (
              <button
                className="btn-ghost mt-3 w-full text-xs"
                onClick={() => openExternal(offer.source_url)}
              >
                <Icon name="doc" className="h-4 w-4" /> Источник условий
              </button>
            )}
          </section>
        </>
      )}
    </div>
  );
}