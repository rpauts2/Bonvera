import { useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDateTime, rub } from "../lib/api";
import { useLoad } from "../lib/useLoad";
import { validateWithdrawal } from "../lib/validation";
import type { Withdrawal, WithdrawalsData } from "../lib/types";
import { useSession } from "../state/session";
import { Icon } from "../components/Icon";
import { EmptyState, ErrorState, ListSkeleton, PageHeader, SectionTitle } from "../components/ui";
import { haptic, hapticNotify, showAlert, showConfirm } from "../lib/telegram";

export default function Withdraw() {
  const { data, error, reload, setData } = useLoad<WithdrawalsData>("/withdrawals");
  const { user } = useSession();
  const [amount, setAmount] = useState("");
  const [bank, setBank] = useState("");
  const [phone, setPhone] = useState("");
  const [useSaved, setUseSaved] = useState(true);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const hasSavedPhone = Boolean(user?.sbp_phone_masked);
  const available = data?.available ?? 0;
  const minWd = data?.min_withdraw ?? 300;

  async function createRequest() {
    if (!data) return;
    setFormError(null);
    const check = validateWithdrawal({
      amount,
      min: minWd,
      available,
      bank: bank || user?.sbp_bank || "",
      phone,
      useSaved,
      hasSavedPhone,
    });
    if (!check.ok) {
      setFormError(check.message);
      return;
    }
    setBusy(true);
    haptic("medium");
    try {
      const created = await api.post<Withdrawal>("/withdrawals", {
        amount: check.amount,
        bank: check.bank,
        phone: check.phone,
      });
      setData((prev) =>
        prev
          ? { ...prev, available: prev.available - check.amount, requests: [created, ...prev.requests] }
          : prev,
      );
      setAmount("");
      setPhone("");
      hapticNotify("success");
      showAlert("Заявка на вывод создана. Администратор проверит её и выполнит перевод вручную по СБП.");
      void reload();
    } catch (e) {
      hapticNotify("error");
      setFormError(e instanceof Error ? e.message : "Не удалось создать заявку на вывод.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel(w: Withdrawal) {
    const ok = await showConfirm(`Отменить заявку на вывод ${rub(w.amount)}? Сумма вернётся в доступный баланс.`);
    if (!ok) return;
    haptic("medium");
    try {
      await api.post(`/withdrawals/${w.id}/cancel`);
      hapticNotify("success");
      void reload();
    } catch (e) {
      hapticNotify("error");
      showAlert(e instanceof Error ? e.message : "Не удалось отменить заявку.");
    }
  }

  return (
    <div>
      <PageHeader title="Вывод средств" subtitle="Перевод по СБП после проверки" back="/wallet" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!data && !error && <ListSkeleton rows={3} />}
      {data && (
        <>
          <section className="px-5">
            <div className="card-gold p-5">
              <div className="text-xs font-semibold uppercase tracking-wider text-indigo-300/70">
                Доступно к выводу
              </div>
              <div className="mt-1 text-3xl font-extrabold text-gold-gradient">{rub(available)}</div>

              <div className="mt-4 space-y-3">
                <div>
                  <label className="mb-1.5 block text-[12px] font-bold text-indigo-300/75" htmlFor="wd-amount">
                    Сумма (от {rub(minWd)})
                  </label>
                  <input
                    id="wd-amount"
                    className="input-dark"
                    inputMode="decimal"
                    placeholder={`${minWd}`}
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-[12px] font-bold text-indigo-300/75" htmlFor="wd-bank">
                    Банк получателя
                  </label>
                  <select
                    id="wd-bank"
                    className="input-dark appearance-none"
                    value={bank || user?.sbp_bank || ""}
                    onChange={(e) => setBank(e.target.value)}
                  >
                    <option value="" className="bg-navy-900">
                      Выбери банк…
                    </option>
                    {data.banks.map((b) => (
                      <option key={b} value={b} className="bg-navy-900">
                        {b}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1.5 block text-[12px] font-bold text-indigo-300/75" htmlFor="wd-phone">
                    Телефон СБП
                  </label>
                  {hasSavedPhone && (
                    <label className="mb-2 flex items-center gap-2 text-xs text-indigo-200/70">
                      <input
                        type="checkbox"
                        checked={useSaved}
                        onChange={(e) => setUseSaved(e.target.checked)}
                        className="h-4 w-4 accent-[#22d3ee]"
                      />
                      Использовать сохранённый ({user?.sbp_phone_masked})
                    </label>
                  )}
                  {(!hasSavedPhone || !useSaved) && (
                    <input
                      id="wd-phone"
                      className="input-dark"
                      inputMode="tel"
                      placeholder="+7 900 000-00-00"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                    />
                  )}
                </div>

                {formError && (
                  <div className="rounded-2xl border border-rose-alert/30 bg-rose-alert/10 p-3 text-xs text-rose-alert">
                    {formError}
                  </div>
                )}

                <button className="btn-gold w-full" disabled={busy} onClick={() => void createRequest()}>
                  <Icon name="arrow-up" className="h-4 w-4" />
                  {busy ? "Создаю заявку…" : "Создать заявку на вывод"}
                </button>
              </div>
            </div>
          </section>

          <section className="px-5 pt-3">
            <div className="card-glass flex gap-2.5 p-4 text-[12px] leading-relaxed text-indigo-200/65">
              <Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
              <span>
                Выплаты выполняются вручную банковским переводом по СБП после проверки администратором.
                Это не мгновенный автоматический вывод. Сумма резервируется на время обработки заявки.
              </span>
            </div>
          </section>

          <SectionTitle>Мои заявки на вывод</SectionTitle>
          {data.requests.length === 0 ? (
            <EmptyState
              icon="wallet"
              title="Заявок пока нет"
              text={`Накопи минимум ${rub(minWd)} на доступном балансе и создай первую заявку.`}
            />
          ) : (
            <div className="space-y-2 px-5 pb-8">
              {data.requests.map((w) => (
                <div key={w.id} className="card-glass p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-extrabold">{rub(w.amount)}</div>
                      <div className="truncate text-[12px] text-indigo-300/70">
                        {w.bank} · {fmtDateTime(w.created)}
                      </div>
                      {w.paid_at && (
                        <div className="text-[12px] text-emerald-glow/80">выплачено {fmtDateTime(w.paid_at)}</div>
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
                    <button className="btn-ghost mt-3 w-full py-2.5 text-xs" onClick={() => void cancel(w)}>
                      <Icon name="cross" className="h-3.5 w-3.5" /> Отменить заявку
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {!hasSavedPhone && (
            <p className="px-5 pb-6 text-center text-[12px] text-indigo-300/70">
              Сохрани банк и телефон в{" "}
              <Link to="/settings" className="font-bold text-electric">
                настройках СБП
              </Link>
              , чтобы выводить быстрее.
            </p>
          )}
        </>
      )}
    </div>
  );
}