import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDateTime, rub } from "../lib/api";
import { useLoad } from "../lib/useLoad";
import type { UserProfile, WalletData, Withdrawal, WithdrawalsData } from "../lib/types";
import { useSession } from "../state/session";
import { Icon } from "../components/Icon";
import {
  EmptyState,
  ErrorState,
  ListSkeleton,
  PageHeader,
  ProgressBar,
  SectionTitle,
} from "../components/ui";
import { haptic, hapticNotify, showAlert, showConfirm } from "../lib/telegram";

/** Быстрые суммы, которые видит пользователь. Недоступные варианты блокируются. */
const QUICK_AMOUNTS = [500, 1000] as const;

/** Три шага выплаты — без сроков, которых нет в API. */
const STEPS = [
  {
    title: "Заявка",
    text: "Указываешь сумму и реквизиты СБП. Сумма сразу резервируется на балансе и больше не входит в доступные.",
  },
  {
    title: "Проверка вручную",
    text: "Администратор сверяет заявку и реквизиты. Пока заявка ждёт проверки, её можно отменить — сумма вернётся на баланс.",
  },
  {
    title: "Перевод по СБП",
    text: "Деньги отправляются на указанный номер телефона. После перевода статус заявки меняется на «Выплачено».",
  },
] as const;

type Field = "amount" | "bank" | "phone";
type ProfileSave = "idle" | "saved" | "failed";

type AmountParse =
  | { kind: "empty" }
  | { kind: "format" }
  | { kind: "fraction" }
  | { kind: "value"; value: number };

/**
 * Разбор суммы: в поле можно вставить «1 000» или «500,00», но API принимает
 * только целые рубли, поэтому дробная сумма объясняется отдельной ошибкой.
 */
function parseAmount(raw: string): AmountParse {
  const cleaned = raw.replace(/[\s\u00A0]/g, "").replace(",", ".");
  if (!cleaned) return { kind: "empty" };
  if (!/^\d+(?:\.\d*)?$/.test(cleaned)) return { kind: "format" };
  const value = Number(cleaned);
  if (!Number.isFinite(value)) return { kind: "format" };
  if (!Number.isInteger(value)) return { kind: "fraction" };
  return { kind: "value", value };
}

function amountProblem(parsed: AmountParse, min: number, available: number): string | null {
  switch (parsed.kind) {
    case "empty":
      return "Введи сумму вывода.";
    case "format":
      return "Сумма — только цифры, например 1000.";
    case "fraction":
      return "Выводим целыми рублями, без копеек.";
    case "value":
      if (parsed.value <= 0) return "Сумма должна быть больше нуля.";
      if (parsed.value < min) return `Минимум для вывода — ${rub(min)}.`;
      if (parsed.value > available) return `Доступно только ${rub(available)}.`;
      return null;
  }
}

/** Приводит ввод к виду +7XXXXXXXXXX, который ждёт API. */
function normalizePhone(raw: string): string | null {
  const digits = raw.replace(/\D/g, "");
  const full =
    digits.length === 11 && digits.startsWith("8")
      ? `7${digits.slice(1)}`
      : digits.length === 10
        ? `7${digits}`
        : digits;
  return full.length === 11 && full.startsWith("7") ? full : null;
}

function maskPhone(normalized: string): string {
  return `+7 ${normalized.slice(1, 4)} •••-${normalized.slice(7, 9)}-${normalized.slice(9, 11)}`;
}

export default function Withdraw() {
  const {
    data: wallet,
    error: walletError,
    reload: reloadWallet,
    setData: setWallet,
  } = useLoad<WalletData>("/wallet");
  const {
    data: withdrawals,
    error: withdrawalsError,
    reload: reloadWithdrawals,
    setData: setWithdrawals,
  } = useLoad<WithdrawalsData>("/withdrawals");
  const { data: me, setData: setMe } = useLoad<UserProfile>("/me");
  const { user } = useSession();
  /** Свежий профиль из /me, локальный снимок сессии — запасной вариант. */
  const profile = me ?? user;

  const [amount, setAmount] = useState("");
  const [bank, setBank] = useState(user?.sbp_bank ?? "");
  const [phone, setPhone] = useState("");
  const [useSaved, setUseSaved] = useState(true);
  const [saveToProfile, setSaveToProfile] = useState(true);
  const [bankTouched, setBankTouched] = useState(false);
  const [touched, setTouched] = useState<Record<Field, boolean>>({
    amount: false,
    bank: false,
    phone: false,
  });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [created, setCreated] = useState<Withdrawal | null>(null);
  const [createdPhone, setCreatedPhone] = useState<string | null>(null);
  const [profileSave, setProfileSave] = useState<ProfileSave>("idle");

  const available = wallet?.summary.available ?? withdrawals?.available ?? 0;
  const minWd = wallet?.summary.min_withdraw ?? withdrawals?.min_withdraw ?? 300;
  const hold = wallet?.summary.hold ?? 0;
  const review = wallet?.summary.review ?? 0;
  const banks = withdrawals?.banks ?? [];

  const savedPhone = profile?.sbp_phone_masked ?? null;
  const reuseSavedPhone = Boolean(savedPhone) && useSaved;

  // Банк из профиля подставляется один раз и не перебивает выбор пользователя.
  const savedBank = profile?.sbp_bank ?? "";
  useEffect(() => {
    if (bankTouched || !savedBank) return;
    setBank((prev) => prev || savedBank);
  }, [bankTouched, savedBank]);

  const parsed = parseAmount(amount);
  const amountError = amountProblem(parsed, minWd, available);
  const bankError = bank.trim().length >= 2 ? null : "Выбери банк для перевода по СБП.";
  const normalizedPhone = normalizePhone(phone);
  const phoneError = reuseSavedPhone
    ? null
    : phone.trim() === ""
      ? "Укажи телефон СБП или используй сохранённый."
      : normalizedPhone === null
        ? "Нужен номер из 11 цифр, например +79991234567."
        : null;

  const canSubmit =
    available >= minWd && amountError === null && bankError === null && phoneError === null;
  const showAmountError = touched.amount || amount.trim() !== "";
  const showPhoneError = touched.phone || (phone.trim() !== "" && !reuseSavedPhone);

  function touch(field: Field) {
    setTouched((prev) => (prev[field] ? prev : { ...prev, [field]: true }));
  }

  async function submit() {
    setFormError(null);
    setTouched({ amount: true, bank: true, phone: true });
    if (!canSubmit || parsed.kind !== "value") return;
    const chosenBank = bank.trim();
    const chosenPhone = reuseSavedPhone ? null : normalizedPhone;
    setBusy(true);
    haptic("medium");
    try {
      const view = await api.post<Withdrawal>("/withdrawals", {
        amount: parsed.value,
        bank: chosenBank,
        phone: chosenPhone,
      });
      setCreated(view);
      setCreatedPhone(reuseSavedPhone ? savedPhone : chosenPhone ? maskPhone(chosenPhone) : null);
      setProfileSave("idle");
      setAmount("");
      setPhone("");
      setTouched({ amount: false, bank: false, phone: false });
      setWallet((prev) =>
        prev
          ? {
              ...prev,
              summary: {
                ...prev.summary,
                available: Math.max(0, prev.summary.available - view.amount),
              },
            }
          : prev,
      );
      setWithdrawals((prev) =>
        prev
          ? {
              ...prev,
              available: Math.max(0, prev.available - view.amount),
              requests: [view, ...prev.requests.filter((r) => r.id !== view.id)],
            }
          : prev,
      );
      hapticNotify("success");

      // Заявка уже создана: неудачное сохранение профиля не отменяет выплату.
      if (saveToProfile && (chosenBank !== savedBank || chosenPhone !== null)) {
        try {
          const updated = await api.put<UserProfile>("/me/sbp", {
            bank: chosenBank,
            phone: chosenPhone,
          });
          setMe(updated);
          setProfileSave("saved");
        } catch {
          setProfileSave("failed");
        }
      }

      void reloadWithdrawals();
      void reloadWallet();
    } catch (e) {
      hapticNotify("error");
      setFormError(e instanceof Error ? e.message : "Не удалось создать заявку на вывод.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel(w: Withdrawal) {
    const ok = await showConfirm(
      `Отменить заявку №${w.id} на ${rub(w.amount)}? Сумма вернётся в доступный баланс.`,
    );
    if (!ok) return;
    haptic("medium");
    try {
      await api.post(`/withdrawals/${w.id}/cancel`);
      hapticNotify("success");
      void reloadWithdrawals();
      void reloadWallet();
    } catch (e) {
      hapticNotify("error");
      showAlert(e instanceof Error ? e.message : "Не удалось отменить заявку.");
    }
  }

  function openRequests() {
    setCreated(null);
    setProfileSave("idle");
    haptic("light");
    document
      .getElementById("withdraw-requests")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const booted = wallet !== null || withdrawals !== null;
  const bootError = !booted ? walletError ?? withdrawalsError : null;

  return (
    <div>
      <PageHeader title="Вывод средств" subtitle="Перевод по СБП после проверки" back="/wallet" />
      {bootError && (
        <ErrorState
          message={bootError}
          onRetry={() => {
            void reloadWallet();
            void reloadWithdrawals();
          }}
        />
      )}
      {!booted && !bootError && <ListSkeleton rows={3} />}
      {booted && (
        <>
          <section className="px-5">
            <div className="card-gold relative overflow-hidden p-5">
              <div className="absolute -right-10 -top-12 h-40 w-40 rounded-full bg-gold/10 blur-2xl" />
              <div className="relative">
                <div className="text-xs font-semibold uppercase tracking-wider text-indigo-300/70">
                  Доступно к выводу
                </div>
                <div className="mt-1 text-4xl font-extrabold text-gold-gradient">{rub(available)}</div>
                <div className="mt-1 text-[12px] text-indigo-300/70">
                  минимальная сумма — {rub(minWd)}
                </div>

                {wallet && (
                  <>
                    <dl className="mt-4 space-y-2 border-t border-royal/20 pt-3">
                      <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-[13px] text-indigo-200/80">В холде</dt>
                        <dd className="text-sm font-bold text-gold">{rub(hold)}</dd>
                      </div>
                      <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-[13px] text-indigo-200/80">На проверке</dt>
                        <dd className="text-sm font-bold text-royal-soft">{rub(review)}</dd>
                      </div>
                    </dl>
                    <p className="mt-2 text-[11px] leading-relaxed text-indigo-300/55">
                      В холде — награды, которые ещё подтверждает партнёр. На проверке — задания,
                      которые смотрит администратор. Эти суммы станут доступны только после
                      подтверждения.
                    </p>
                  </>
                )}
              </div>
            </div>
          </section>

          {created ? (
            <section className="px-5 pt-3">
              <div className="card-gold p-5 text-center">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-glow/15 text-emerald-glow">
                  <Icon name="check" className="h-7 w-7" />
                </div>
                <div className="mt-3 text-lg font-extrabold">Заявка на вывод создана</div>
                <div className="mt-1 text-3xl font-extrabold text-gold-gradient">{rub(created.amount)}</div>
                <div className="mt-2 inline-flex items-center rounded-full border border-gold/30 bg-gold/10 px-3 py-1 text-[12px] font-bold text-gold">
                  Заявка №{created.id} · {created.status_ru}
                </div>
                <dl className="mt-4 space-y-2 rounded-2xl bg-navy-950/50 p-3 text-left">
                  <div className="flex justify-between gap-3 text-[12px]">
                    <dt className="text-indigo-300/70">Банк</dt>
                    <dd className="font-bold">{created.bank}</dd>
                  </div>
                  <div className="flex justify-between gap-3 text-[12px]">
                    <dt className="text-indigo-300/70">Телефон</dt>
                    <dd className="font-bold">{createdPhone ?? "—"}</dd>
                  </div>
                  <div className="flex justify-between gap-3 text-[12px]">
                    <dt className="text-indigo-300/70">Создана</dt>
                    <dd className="font-bold">{fmtDateTime(created.created)}</dd>
                  </div>
                </dl>
                {profileSave === "saved" && (
                  <p className="mt-2 text-[12px] font-semibold text-emerald-glow">
                    Реквизиты сохранены в профиль.
                  </p>
                )}
                {profileSave === "failed" && (
                  <p className="mt-2 text-[12px] leading-relaxed text-gold">
                    Заявка создана, но реквизиты не сохранились в профиль — обнови их в настройках СБП.
                  </p>
                )}
                <p className="mt-3 text-[12px] leading-relaxed text-indigo-200/70">
                  Администратор проверит реквизиты и выполнит перевод по СБП. Номер заявки и решение
                  останутся в списке ниже.
                </p>
                <button className="btn-gold mt-4 min-h-12 w-full" onClick={openRequests}>
                  <Icon name="doc" className="h-4 w-4" /> Мои заявки
                </button>
                {available >= minWd && (
                  <button
                    className="btn-ghost mt-2 min-h-12 w-full"
                    onClick={() => {
                      setCreated(null);
                      setProfileSave("idle");
                    }}
                  >
                    Вывести ещё
                  </button>
                )}
              </div>
            </section>
          ) : available < minWd ? (
            <section className="px-5 pt-3">
              <div className="card-glass p-5">
                <div className="text-sm font-extrabold">Пока недостаточно средств</div>
                <p className="mt-1 text-[12px] leading-relaxed text-indigo-300/70">
                  Для заявки нужно минимум {rub(minWd)}. Осталось накопить{" "}
                  {rub(Math.max(0, minWd - available))}.
                </p>
                <div className="mt-3">
                  <ProgressBar value={available} max={minWd} gold />
                </div>
                <Link to="/catalog" className="btn-primary mt-4 min-h-12 w-full" onClick={() => haptic("light")}>
                  <Icon name="catalog" className="h-4 w-4" /> Выбрать предложение
                </Link>
              </div>
            </section>
          ) : (
            <>
              <section className="px-5 pt-3">
                <div className="card-glass p-5">
                  <div className="flex items-baseline justify-between gap-3">
                    <label className="text-sm font-extrabold" htmlFor="wd-amount">
                      Сумма вывода
                    </label>
                    <span className="text-[12px] text-indigo-300/70">от {rub(minWd)}</span>
                  </div>
                  <div className="mt-2 flex items-stretch gap-2">
                    <input
                      id="wd-amount"
                      className="input-dark min-w-0 flex-1"
                      inputMode="numeric"
                      autoComplete="off"
                      maxLength={12}
                      placeholder={String(minWd)}
                      value={amount}
                      onChange={(e) => {
                        setAmount(e.target.value);
                        touch("amount");
                      }}
                      onBlur={() => touch("amount")}
                      aria-invalid={showAmountError && amountError !== null}
                      aria-describedby="wd-amount-hint"
                    />
                    <span className="flex shrink-0 items-center rounded-2xl border border-royal/25 bg-navy-900/60 px-3 text-sm font-bold text-indigo-200/80">
                      ₽
                    </span>
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    {QUICK_AMOUNTS.map((value) => (
                      <button
                        key={value}
                        type="button"
                        className="min-h-11 rounded-2xl border border-royal/25 bg-navy-900/60 px-2 text-[13px] font-bold text-indigo-100 transition active:scale-[0.97] disabled:opacity-35"
                        disabled={busy || value < minWd || value > available}
                        onClick={() => {
                          setAmount(String(value));
                          touch("amount");
                          haptic("light");
                        }}
                      >
                        {rub(value)}
                      </button>
                    ))}
                    <button
                      type="button"
                      className="min-h-11 rounded-2xl border border-royal/25 bg-navy-900/60 px-2 text-[13px] font-bold text-indigo-100 transition active:scale-[0.97] disabled:opacity-35"
                      disabled={busy || available < minWd}
                      onClick={() => {
                        setAmount(String(available));
                        touch("amount");
                        haptic("light");
                      }}
                    >
                      Всё
                    </button>
                  </div>
                  <p id="wd-amount-hint" className="mt-2 text-[11px] text-indigo-300/55">
                    Доступно: {rub(available)}. Вывод — целыми рублями.
                  </p>
                  {showAmountError && amountError && (
                    <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-[12px] font-semibold text-rose-alert">
                      <Icon name="cross" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      {amountError}
                    </p>
                  )}
                </div>
              </section>

              <section className="px-5 pt-3">
                <div className="card-glass space-y-4 p-5">
                  <div>
                    <label className="mb-1.5 block text-sm font-extrabold" htmlFor="wd-bank">
                      Банк для СБП
                    </label>
                    <select
                      id="wd-bank"
                      className="input-dark appearance-none"
                      value={bank}
                      onChange={(e) => {
                        setBank(e.target.value);
                        setBankTouched(true);
                        touch("bank");
                      }}
                      onBlur={() => touch("bank")}
                      aria-invalid={touched.bank && bankError !== null}
                    >
                      <option value="" className="bg-navy-900">
                        Выбери банк…
                      </option>
                      {banks.map((b) => (
                        <option key={b} value={b} className="bg-navy-900">
                          {b}
                        </option>
                      ))}
                    </select>
                    {touched.bank && bankError && (
                      <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-[12px] font-semibold text-rose-alert">
                        <Icon name="cross" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                        {bankError}
                      </p>
                    )}
                    {!withdrawals && withdrawalsError && (
                      <p className="mt-1.5 text-[11px] text-indigo-300/60">
                        Список банков не загрузился.{" "}
                        <button
                          type="button"
                          className="font-bold text-electric"
                          onClick={() => void reloadWithdrawals()}
                        >
                          Повторить
                        </button>
                      </p>
                    )}
                  </div>

                  <div>
                    <label className="mb-1.5 block text-sm font-extrabold" htmlFor="wd-phone">
                      Телефон СБП
                    </label>
                    {savedPhone && (
                      <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-2xl border border-royal/20 bg-navy-950/40 px-3">
                        <input
                          type="checkbox"
                          className="h-5 w-5 shrink-0 accent-[#22d3ee]"
                          checked={useSaved}
                          onChange={(e) => {
                            setUseSaved(e.target.checked);
                            if (!e.target.checked) setPhone("");
                            haptic("light");
                          }}
                        />
                        <span className="min-w-0 flex-1 py-2 text-[12px] leading-snug text-indigo-200/80">
                          Использовать сохранённый номер
                          <span className="block text-indigo-300/60">{savedPhone}</span>
                        </span>
                      </label>
                    )}
                    {!reuseSavedPhone && (
                      <>
                        <input
                          id="wd-phone"
                          className="input-dark mt-2"
                          inputMode="tel"
                          autoComplete="tel"
                          maxLength={20}
                          placeholder="+7XXXXXXXXXX"
                          value={phone}
                          onChange={(e) => {
                            setPhone(e.target.value);
                            touch("phone");
                          }}
                          onBlur={() => touch("phone")}
                          aria-invalid={showPhoneError && phoneError !== null}
                          aria-describedby="wd-phone-hint"
                        />
                        <p id="wd-phone-hint" className="mt-1.5 text-[11px] text-indigo-300/55">
                          Формат: +7XXXXXXXXXX — 11 цифр. Номер должен быть привязан к СБП.
                        </p>
                        {showPhoneError && phoneError && (
                          <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-[12px] font-semibold text-rose-alert">
                            <Icon name="cross" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            {phoneError}
                          </p>
                        )}
                      </>
                    )}
                  </div>

                  <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-2xl border border-royal/20 bg-navy-950/40 px-3">
                    <input
                      type="checkbox"
                      className="h-5 w-5 shrink-0 accent-[#22d3ee]"
                      checked={saveToProfile}
                      onChange={(e) => {
                        setSaveToProfile(e.target.checked);
                        haptic("light");
                      }}
                    />
                    <span className="min-w-0 flex-1 py-2 text-[12px] leading-snug text-indigo-200/80">
                      Сохранить реквизиты в профиль
                      <span className="block text-indigo-300/60">Подставим их в следующий раз</span>
                    </span>
                  </label>
                </div>
              </section>

              <section className="px-5 pt-3">
                <button
                  className="btn-gold min-h-12 w-full"
                  disabled={busy || !canSubmit}
                  onClick={() => void submit()}
                >
                  <Icon name="arrow-up" className="h-4 w-4" />
                  {busy ? "Отправляю…" : "Вывести"}
                </button>
                {!canSubmit && (
                  <p className="mt-2 text-center text-[11px] text-indigo-300/55">
                    Кнопка станет активной, когда сумма и реквизиты будут заполнены верно.
                  </p>
                )}
                {formError && (
                  <div
                    role="alert"
                    className="mt-2 rounded-2xl border border-rose-alert/30 bg-rose-alert/10 p-3 text-xs text-rose-alert"
                  >
                    {formError}
                  </div>
                )}
              </section>
            </>
          )}

          <SectionTitle>Как это работает</SectionTitle>
          <section className="px-5">
            <ol className="card-glass space-y-3 p-5">
              {STEPS.map((step, index) => (
                <li key={step.title} className="flex gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-gold/10 text-[12px] font-extrabold text-gold">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-bold text-indigo-100">{step.title}</div>
                    <p className="mt-0.5 text-[12px] leading-relaxed text-indigo-300/65">{step.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <div id="withdraw-requests" className="scroll-mt-4">
            <SectionTitle>Мои заявки на вывод</SectionTitle>
            {!withdrawals ? (
              withdrawalsError ? (
                <div className="px-5">
                  <ErrorState message={withdrawalsError} onRetry={() => void reloadWithdrawals()} />
                </div>
              ) : (
                <ListSkeleton rows={2} />
              )
            ) : withdrawals.requests.length === 0 ? (
              <EmptyState
                icon="wallet"
                title="Заявок пока нет"
                text={`Накопи минимум ${rub(minWd)} на доступном балансе и создай первую заявку.`}
              />
            ) : (
              <div className="space-y-2 px-5 pb-8">
                {withdrawals.requests.map((w) => (
                  <div key={w.id} className="card-glass p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-extrabold">
                          {rub(w.amount)}
                          <span className="ml-2 text-[12px] font-bold text-indigo-300/60">№{w.id}</span>
                        </div>
                        <div className="truncate text-[12px] text-indigo-300/70">
                          {w.bank} · {fmtDateTime(w.created)}
                        </div>
                        {w.paid_at && (
                          <div className="text-[12px] text-emerald-glow/80">
                            выплачено {fmtDateTime(w.paid_at)}
                          </div>
                        )}
                      </div>
                      <span
                        className={`shrink-0 rounded-full border px-2.5 py-1 text-[12px] font-bold ${
                          w.status === "paid"
                            ? "border-emerald-glow/40 bg-emerald-glow/10 text-emerald-glow"
                            : w.status === "rejected" || w.status === "cancelled"
                              ? "border-rose-alert/30 bg-rose-alert/10 text-rose-alert"
                              : "border-gold/30 bg-gold/10 text-gold"
                        }`}
                      >
                        {w.status_ru}
                      </span>
                    </div>
                    {w.admin_note && (
                      <div className="mt-2 rounded-xl bg-navy-950/60 p-2.5 text-[12px] text-indigo-200/65">
                        {w.admin_note}
                      </div>
                    )}
                    {w.can_cancel && (
                      <button
                        className="btn-ghost mt-3 min-h-11 w-full py-2.5 text-xs"
                        onClick={() => void cancel(w)}
                      >
                        <Icon name="cross" className="h-3.5 w-3.5" /> Отменить заявку
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {!savedPhone && (
            <p className="px-5 pb-6 text-center text-[12px] text-indigo-300/70">
              Сохрани банк и телефон в{" "}
              <Link to="/settings" className="font-bold text-electric">
                настройках СБП
              </Link>
              , чтобы в следующий раз не вводить их вручную.
            </p>
          )}
        </>
      )}
    </div>
  );
}
