import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useLoad } from "../lib/useLoad";
import type { MetaInfo, UserProfile } from "../lib/types";
import { useSession } from "../state/session";
import { Icon } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader, SectionTitle } from "../components/ui";
import { haptic, hapticNotify, showAlert } from "../lib/telegram";

export default function Settings() {
  const { user, refresh } = useSession();
  const { data: meta, error, reload } = useLoad<MetaInfo>("/meta");
  const [bank, setBank] = useState(user?.sbp_bank ?? "");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function save() {
    setFormError(null);
    if (!bank) {
      setFormError("Выбери банк.");
      return;
    }
    if (!phone.trim() && !user?.sbp_phone_masked) {
      setFormError("Укажи телефон, привязанный к СБП.");
      return;
    }
    setBusy(true);
    haptic("medium");
    try {
      await api.put<UserProfile>("/me/sbp", { bank, phone: phone.trim() || null });
      await refresh();
      setPhone("");
      hapticNotify("success");
      showAlert("Настройки СБП сохранены. Телефон хранится в зашифрованном виде.");
    } catch (e) {
      hapticNotify("error");
      setFormError(e instanceof Error ? e.message : "Не удалось сохранить настройки.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Настройки СБП" subtitle="Реквизиты для выплат" back="/profile" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!meta && !error && <ListSkeleton rows={2} />}
      {meta && (
        <>
          <section className="px-5">
            <div className="card-glass space-y-3 p-5">
              <div>
                <label className="mb-1.5 block text-[11px] font-bold text-indigo-300/60" htmlFor="sbp-bank">
                  Банк получателя
                </label>
                <select
                  id="sbp-bank"
                  className="input-dark appearance-none"
                  value={bank}
                  onChange={(e) => setBank(e.target.value)}
                >
                  <option value="" className="bg-navy-900">
                    Выбери банк…
                  </option>
                  {meta.banks.map((b) => (
                    <option key={b} value={b} className="bg-navy-900">
                      {b}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-[11px] font-bold text-indigo-300/60" htmlFor="sbp-phone">
                  Телефон СБП {user?.sbp_phone_masked && `(сейчас: ${user.sbp_phone_masked})`}
                </label>
                <input
                  id="sbp-phone"
                  className="input-dark"
                  inputMode="tel"
                  placeholder={user?.sbp_phone_masked ? "Оставь пустым, чтобы не менять" : "+7 900 000-00-00"}
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </div>
              {formError && (
                <div className="rounded-2xl border border-rose-alert/30 bg-rose-alert/10 p-3 text-xs text-rose-alert">
                  {formError}
                </div>
              )}
              <button className="btn-primary w-full" disabled={busy} onClick={() => void save()}>
                <Icon name="check" className="h-4 w-4" /> {busy ? "Сохраняю…" : "Сохранить"}
              </button>
            </div>
          </section>

          <section className="px-5 pt-3">
            <div className="card-glass flex gap-2.5 p-4 text-[11px] leading-relaxed text-indigo-200/65">
              <Icon name="lock" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-glow" />
              <span>
                Телефон шифруется и используется только для переводов по СБП. Мы никогда не запрашиваем
                паспортные данные, CVV/CVC, PIN-коды, пароли и коды из SMS.
              </span>
            </div>
          </section>

          <SectionTitle>Документы</SectionTitle>
          <section className="space-y-2 px-5 pb-8">
            <Link to="/rules" className="card-glass flex items-center gap-3 p-4" onClick={() => haptic("light")}>
              <Icon name="doc" className="h-5 w-5 text-royal-soft" />
              <span className="flex-1 text-sm font-bold">Правила сервиса</span>
              <Icon name="chevron-right" className="h-4 w-4 text-indigo-300/40" />
            </Link>
            <Link to="/support" className="card-glass flex items-center gap-3 p-4" onClick={() => haptic("light")}>
              <Icon name="support" className="h-5 w-5 text-royal-soft" />
              <span className="flex-1 text-sm font-bold">Поддержка</span>
              <Icon name="chevron-right" className="h-4 w-4 text-indigo-300/40" />
            </Link>
          </section>
        </>
      )}
    </div>
  );
}