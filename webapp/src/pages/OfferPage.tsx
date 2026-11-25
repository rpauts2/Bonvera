import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { ageRangeLabel, uniqueOfferDetails } from "../lib/format";
import { useLoad } from "../lib/useLoad";
import type { OfferDetail, TakeResult, UserProfile } from "../lib/types";
import { useSession } from "../state/session";
import { Icon } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader, SectionTitle } from "../components/ui";
import { haptic, hapticNotify, openExternal } from "../lib/telegram";

const CAT_LABEL: Record<string, string> = {
  cards: "Банковская карта",
  bk: "Букмекер",
  mfo: "Займ МФО",
  cpl: "CPL-заявка",
};

/** Заголовки трёх шагов оформления: условия → что понадобится → подтверждение. */
const CHECKOUT_STEPS = ["Условия", "Что понадобится", "Подтверждение"];

export default function OfferPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, refresh } = useSession();
  const { data: offer, error, reload } = useLoad<OfferDetail>(`/offers/${id}`);
  const [taking, setTaking] = useState(false);
  const [needAge, setNeedAge] = useState(false);
  const [ageInput, setAgeInput] = useState("");
  const [ageSaving, setAgeSaving] = useState(false);
  const [step, setStep] = useState<number | null>(null);
  const [agreed, setAgreed] = useState<boolean[]>([false, false, false]);
  const [takeError, setTakeError] = useState<string | null>(null);

  // Диалог закрывается по Esc так же, как по фону.
  useEffect(() => {
    if (step === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !taking) setStep(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, taking]);

  // Пока диалог открыт, страница под ним не прокручивается.
  useEffect(() => {
    if (step === null) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [step]);

  function openCheckout() {
    haptic("light");
    setAgreed([false, false, false]);
    setTakeError(null);
    setStep(0);
  }

  function closeCheckout() {
    if (taking) return;
    haptic("light");
    setStep(null);
    setTakeError(null);
  }

  function toggleAgreed(index: number) {
    haptic("light");
    setAgreed((prev) => prev.map((value, i) => (i === index ? !value : value)));
  }

  async function take() {
    if (!offer) return;
    setTaking(true);
    setTakeError(null);
    haptic("medium");
    try {
      const res = await api.post<TakeResult>(`/offers/${offer.id}/take`);
      hapticNotify("success");
      setStep(null);
      navigate(`/apps/${res.app_id}`);
    } catch (e) {
      hapticNotify("error");
      if (e instanceof ApiError && e.code === "age_required") {
        setNeedAge(true);
      }
      // 409/403 и прочие отказы показываем прямо в диалоге, рядом с кнопкой.
      setTakeError(e instanceof Error ? e.message : "Не удалось создать заявку.");
      void reload();
    } finally {
      setTaking(false);
    }
  }

  async function saveAgeAndTake() {
    const years = Number(ageInput);
    if (!Number.isInteger(years) || years < 18 || years > 120) {
      setTakeError("Укажи число полных лет от 18 до 120.");
      return;
    }
    setAgeSaving(true);
    setTakeError(null);
    try {
      await api.put<UserProfile>("/me/age", { years });
      await refresh();
      setNeedAge(false);
      await take();
    } catch (e) {
      setTakeError(e instanceof Error ? e.message : "Не удалось сохранить возраст.");
    } finally {
      setAgeSaving(false);
    }
  }

  const ageBlocked =
    offer && user?.age_years != null && (user.age_years < offer.age_min || user.age_years > offer.age_max);
  const conditionText = offer?.condition?.trim() || offer?.action?.trim() || "";
  const extraOfferDetails = uniqueOfferDetails(conditionText, offer?.action, offer?.rules);
  const proofItems =
    offer && offer.required_proofs.length > 0
      ? offer.required_proofs
      : ["Скриншот подтверждения выполнения"];

  return (
    <div>
      <PageHeader title="Предложение" back="/catalog" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!offer && !error && <ListSkeleton rows={3} />}
      {offer && (
        <>
          <section className="px-5">
            <div className="card-glass overflow-hidden">
              <div className="relative aspect-video w-full overflow-hidden bg-[radial-gradient(circle_at_25%_20%,rgba(34,211,238,.18),transparent_42%),linear-gradient(135deg,#17234b,#090e20)]">
                <div className="absolute inset-0 flex items-center justify-center" aria-hidden="true">
                  <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.06] text-3xl font-black text-white/80 shadow-2xl">
                    {offer.brand.trim().charAt(0).toUpperCase() || "B"}
                  </div>
                </div>
                {offer.image_url && (
                  <img
                    src={offer.image_url}
                    alt={offer.brand + " · " + offer.name}
                    onError={(event) => { event.currentTarget.style.display = "none"; }}
                    className="relative z-[1] h-full w-full object-cover"
                  />
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-navy-950 via-navy-950/20 to-transparent" />
                <span className="absolute left-4 top-4 rounded-full border border-white/10 bg-navy-950/80 px-3 py-1 text-[11px] font-bold text-indigo-100 backdrop-blur">
                  {CAT_LABEL[offer.category] ?? offer.category}
                </span>
                {offer.available && (
                  <span className="absolute right-4 top-4 rounded-full border border-emerald-glow/30 bg-navy-950/85 px-3 py-1 text-[10px] font-bold text-emerald-glow backdrop-blur">
                    Можно оформить
                  </span>
                )}
              </div>
              <div className="space-y-4 p-5">
                <div>
                  <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-indigo-300/75">
                    {offer.emoji} {offer.brand}
                  </div>
                  <h2 className="mt-1 text-xl font-extrabold leading-snug text-white">{offer.name}</h2>
                </div>

                <div className="rounded-2xl border border-gold/20 bg-gradient-to-r from-gold/10 via-gold/5 to-transparent p-4">
                  <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold/75">
                    Твоё вознаграждение
                  </div>
                  <div className="mt-1 text-4xl font-black tracking-tight text-gold-gradient">
                    {offer.reward.toLocaleString("ru-RU")} ₽
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-indigo-200/65">
                    Начисление после подтверждения выполнения условий партнёра.
                  </p>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <div className="rounded-2xl border border-white/[0.07] bg-white/[0.035] p-3">
                    <Icon name="clock" className="h-4 w-4 text-electric" />
                    <div className="mt-2 text-sm font-extrabold text-white">{offer.hold_days} дн.</div>
                    <div className="mt-0.5 text-[10px] leading-tight text-indigo-300/65">удержание</div>
                  </div>
                  <div className="rounded-2xl border border-white/[0.07] bg-white/[0.035] p-3">
                    <Icon name="profile" className="h-4 w-4 text-electric" />
                    <div className="mt-2 text-sm font-extrabold text-white">{ageRangeLabel(offer.age_min, offer.age_max)}</div>
                    <div className="mt-0.5 text-[10px] leading-tight text-indigo-300/65">возраст</div>
                  </div>
                  <div className="rounded-2xl border border-white/[0.07] bg-white/[0.035] p-3">
                    <Icon name="check" className="h-4 w-4 text-electric" />
                    <div className="mt-2 text-sm font-extrabold text-white">{offer.purchase_min > 0 ? "от " + offer.purchase_min + " ₽" : "Не требуется"}</div>
                    <div className="mt-0.5 text-[10px] leading-tight text-indigo-300/65">мин. покупка</div>
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

          <SectionTitle>Что нужно сделать</SectionTitle>
          <section className="px-5">
            <div className="card-glass space-y-3 p-5 text-sm leading-relaxed text-indigo-200/80">
              {conditionText && <p className="font-bold text-indigo-100">{conditionText}</p>}
              {extraOfferDetails.map((detail) => (
                <p key={detail} className="whitespace-pre-line text-xs text-indigo-200/65">{detail}</p>
              ))}
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
            {offer.already_taken ? (
              <Link to="/apps" className="btn-primary w-full" onClick={() => haptic("light")}>
                <Icon name="doc" className="h-4 w-4" /> Заявка уже оформлена — открыть
              </Link>
            ) : offer.available && !ageBlocked ? (
              <>
                <button className="btn-gold min-h-11 w-full" onClick={openCheckout}>
                  <Icon name="spark" className="h-4 w-4" /> Получить кэшбэк
                </button>
                <p className="mt-2 text-center text-[12px] leading-relaxed text-indigo-300/75">
                  3 шага: условия, что понадобится, подтверждение. Заявка создаётся только на последнем шаге.
                </p>
              </>
            ) : (
              <div className="space-y-2">
                <button className="btn-gold w-full" disabled>
                  <Icon name="lock" className="h-4 w-4" /> Оформление недоступно
                </button>
                <p className="text-center text-[12px] leading-relaxed text-indigo-300/75">
                  {ageBlocked
                    ? `Предложение доступно для возраста ${ageRangeLabel(offer.age_min, offer.age_max)}.`
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

          {step !== null && (
            <div
              className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 backdrop-blur-sm sm:items-center sm:p-5"
              onClick={closeCheckout}
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="checkout-title"
                onClick={(event) => event.stopPropagation()}
                className="card-glass max-h-[92vh] w-full max-w-[520px] overflow-y-auto rounded-b-none rounded-t-3xl px-5 pt-5 sm:rounded-3xl"
                style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 20px)" }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-electric/80">
                      Шаг {step + 1} из {CHECKOUT_STEPS.length}
                    </div>
                    <h2 id="checkout-title" className="mt-1 text-lg font-extrabold text-white">
                      {CHECKOUT_STEPS[step]}
                    </h2>
                  </div>
                  <button
                    type="button"
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-royal/25 bg-navy-900/70 text-indigo-200"
                    aria-label="Закрыть оформление"
                    onClick={closeCheckout}
                  >
                    <Icon name="cross" className="h-5 w-5" />
                  </button>
                </div>

                <div className="mt-3 flex gap-1.5" aria-hidden="true">
                  {CHECKOUT_STEPS.map((_, i) => (
                    <span
                      key={i}
                      className={`h-1.5 flex-1 rounded-full ${
                        i <= step ? "bg-gradient-to-r from-royal-soft to-electric" : "bg-navy-700"
                      }`}
                    />
                  ))}
                </div>

                {step === 0 && (
                  <div className="mt-4 space-y-4">
                    <p className="whitespace-pre-line text-lg font-extrabold leading-snug text-white">
                      {conditionText || "Выполни условие партнёра и приложи подтверждение."}
                    </p>
                    <div className="grid grid-cols-3 gap-2">
                      <div className="rounded-2xl border border-white/[0.07] bg-white/[0.035] p-3">
                        <Icon name="clock" className="h-4 w-4 text-electric" />
                        <div className="mt-2 text-sm font-extrabold text-white">{offer.hold_days} дн.</div>
                        <div className="mt-0.5 text-[10px] leading-tight text-indigo-300/65">холд</div>
                      </div>
                      <div className="rounded-2xl border border-white/[0.07] bg-white/[0.035] p-3">
                        <Icon name="coin" className="h-4 w-4 text-electric" />
                        <div className="mt-2 text-sm font-extrabold text-white">
                          {offer.purchase_min > 0 ? offer.purchase_min.toLocaleString("ru-RU") + " ₽" : "Не указана"}
                        </div>
                        <div className="mt-0.5 text-[10px] leading-tight text-indigo-300/65">покупка от</div>
                      </div>
                      <div className="rounded-2xl border border-white/[0.07] bg-white/[0.035] p-3">
                        <Icon name="profile" className="h-4 w-4 text-electric" />
                        <div className="mt-2 text-sm font-extrabold text-white">{ageRangeLabel(offer.age_min, offer.age_max)}</div>
                        <div className="mt-0.5 text-[10px] leading-tight text-indigo-300/65">возраст</div>
                      </div>
                    </div>
                    <p className="text-[12px] leading-relaxed text-indigo-300/75">
                      Условие проверяет партнёр. Если оно не выполнено, награда не начисляется.
                    </p>
                    <label className="flex min-h-[56px] cursor-pointer items-start gap-3 rounded-2xl border border-electric/25 bg-electric/[0.07] p-4">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-5 w-5 shrink-0 accent-electric"
                        checked={agreed[0]}
                        onChange={() => toggleAgreed(0)}
                      />
                      <span className="text-[13px] font-semibold leading-snug text-indigo-100">
                        Я понял(а) условия
                      </span>
                    </label>
                  </div>
                )}

                {step === 1 && (
                  <div className="mt-4 space-y-4">
                    <div className="space-y-2">
                      {proofItems.map((proof, i) => (
                        <div
                          key={i}
                          className="flex items-center gap-3 rounded-2xl border border-white/[0.07] bg-white/[0.035] p-3.5"
                        >
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-electric/15 text-electric">
                            <Icon name="camera" className="h-4 w-4" />
                          </span>
                          <span className="text-[13px] font-semibold leading-snug text-indigo-100">{proof}</span>
                        </div>
                      ))}
                    </div>
                    <div className="rounded-2xl border border-gold/25 bg-gold/[0.07] p-4">
                      <div className="flex items-center gap-2 text-[12px] font-extrabold text-gold">
                        <Icon name="clock" className="h-4 w-4" /> Деньги придут после проверки
                      </div>
                      <ul className="mt-2 space-y-1.5 text-[12px] leading-relaxed text-indigo-200/75">
                        <li>Награда начисляется, только когда партнёр подтвердит выполнение условий.</li>
                        <li>Холд {offer.hold_days} дн. — выплата станет доступна после этого срока.</li>
                        <li>Покупки и траты — за свои деньги: сервис их не возвращает.</li>
                      </ul>
                    </div>
                    <label className="flex min-h-[56px] cursor-pointer items-start gap-3 rounded-2xl border border-electric/25 bg-electric/[0.07] p-4">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-5 w-5 shrink-0 accent-electric"
                        checked={agreed[1]}
                        onChange={() => toggleAgreed(1)}
                      />
                      <span className="text-[13px] font-semibold leading-snug text-indigo-100">
                        Я понял(а), что понадобится
                      </span>
                    </label>
                  </div>
                )}

                {step === 2 && (
                  <div className="mt-4 space-y-4">
                    <div className="rounded-2xl border border-white/[0.07] bg-white/[0.035] p-4">
                      <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-indigo-300/70">
                        {offer.emoji} {offer.brand}
                      </div>
                      <div className="mt-1 text-[15px] font-extrabold leading-snug text-white">{offer.name}</div>
                      <div className="mt-3 flex items-end justify-between gap-3">
                        <div>
                          <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold/75">Награда</div>
                          <div className="text-2xl font-black tracking-tight text-gold-gradient">
                            {offer.reward.toLocaleString("ru-RU")} ₽
                          </div>
                        </div>
                        <div className="text-right text-[11px] leading-relaxed text-indigo-300/75">
                          Холд {offer.hold_days} дн.
                          <br />
                          {ageRangeLabel(offer.age_min, offer.age_max)}
                          {offer.purchase_min > 0 && (
                            <>
                              <br />
                              покупка от {offer.purchase_min.toLocaleString("ru-RU")} ₽
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    {takeError && (
                      <div
                        role="alert"
                        className="rounded-2xl border border-rose-alert/35 bg-rose-alert/10 p-4 text-[12px] leading-relaxed text-rose-alert"
                      >
                        {takeError}
                      </div>
                    )}

                    {needAge && (
                      <div className="space-y-2 rounded-2xl border border-royal/25 bg-navy-950/60 p-4">
                        <div className="text-[12px] font-bold text-indigo-100">
                          Подтверди возраст: {ageRangeLabel(offer.age_min, offer.age_max)}
                        </div>
                        <p className="text-[11px] leading-relaxed text-indigo-300/75">
                          Возраст проверяется на сервере и сохраняется в профиле — вводить повторно не потребуется.
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
                          type="button"
                          className="btn-ghost min-h-11 w-full text-xs"
                          disabled={ageSaving || taking}
                          onClick={() => void saveAgeAndTake()}
                        >
                          <Icon name="check" className="h-4 w-4" />
                          {ageSaving || taking ? "Проверяю…" : "Сохранить возраст и оформить"}
                        </button>
                      </div>
                    )}

                    <p className="text-[11px] leading-relaxed text-indigo-300/70">
                      «Оформить» создаёт заявку. Это бесплатно: покупки по условию ты делаешь своими деньгами,
                      а награда приходит после проверки.
                    </p>
                  </div>
                )}

                <div className="mt-5 flex gap-2">
                  {step > 0 && (
                    <button
                      type="button"
                      className="btn-ghost min-h-11 flex-1"
                      disabled={taking || ageSaving}
                      onClick={() => setStep(step - 1)}
                    >
                      <Icon name="chevron-left" className="h-4 w-4" /> Назад
                    </button>
                  )}
                  {step < CHECKOUT_STEPS.length - 1 ? (
                    <button
                      type="button"
                      className="btn-gold min-h-11 flex-1"
                      disabled={!agreed[step]}
                      onClick={() => setStep(step + 1)}
                    >
                      Дальше <Icon name="chevron-right" className="h-4 w-4" />
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn-gold min-h-11 flex-1"
                      disabled={taking || ageSaving || !agreed[0] || !agreed[1]}
                      onClick={() => void take()}
                    >
                      <Icon name="spark" className="h-4 w-4" />
                      {taking ? "Создаю заявку…" : "Оформить"}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
