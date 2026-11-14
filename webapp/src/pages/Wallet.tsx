import { Link } from "react-router-dom";
import { useLoad } from "../lib/useLoad";
import { fmtDateTime, rub } from "../lib/api";
import type { WalletData } from "../lib/types";
import { Icon } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader, SectionTitle } from "../components/ui";
import { haptic } from "../lib/telegram";

export default function Wallet() {
  const { data, error, reload } = useLoad<WalletData>("/wallet");

  return (
    <div>
      <PageHeader title="Кошелёк" subtitle="Реальные деньги, не игровые монеты" back="/profile" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!data && !error && <ListSkeleton rows={3} />}
      {data && (
        <>
          <section className="px-5">
            <div className="card-gold relative overflow-hidden p-5">
              <div className="absolute -right-8 -top-10 h-36 w-36 rounded-full bg-gold/10 blur-2xl" />
              <div className="text-xs font-semibold uppercase tracking-wider text-indigo-300/70">
                Доступно к выводу
              </div>
              <div className="mt-2 text-4xl font-extrabold text-gold-gradient">
                {rub(data.summary.available)}
              </div>
              <div className="mt-1 text-[12px] text-indigo-300/70">
                минимальная сумма вывода — {rub(data.summary.min_withdraw)}
              </div>
              <Link to="/withdraw" className="btn-gold mt-4 w-full" onClick={() => haptic("medium")}>
                <Icon name="arrow-up" className="h-4 w-4" /> Вывести по СБП
              </Link>
            </div>
          </section>

          <section className="mt-3 grid grid-cols-2 gap-3 px-5">
            <div className="card-glass p-4">
              <div className="flex items-center gap-1.5 text-[12px] text-indigo-300/75">
                <Icon name="clock" className="h-3.5 w-3.5 text-gold" /> Холд сети
              </div>
              <div className="mt-1 text-lg font-extrabold text-gold">{rub(data.summary.hold)}</div>
              <div className="mt-0.5 text-[12px] leading-snug text-indigo-300/40">
                ожидание подтверждения партнёрской сетью
              </div>
            </div>
            <div className="card-glass p-4">
              <div className="flex items-center gap-1.5 text-[12px] text-indigo-300/75">
                <Icon name="shield" className="h-3.5 w-3.5 text-royal-soft" /> На проверке
              </div>
              <div className="mt-1 text-lg font-extrabold text-royal-soft">{rub(data.summary.review)}</div>
              <div className="mt-0.5 text-[12px] leading-snug text-indigo-300/40">
                заявка у администратора
              </div>
            </div>
            <div className="card-glass p-4">
              <div className="flex items-center gap-1.5 text-[12px] text-indigo-300/75">
                <Icon name="lock" className="h-3.5 w-3.5 text-electric" /> Зарезервировано
              </div>
              <div className="mt-1 text-lg font-extrabold text-electric">{rub(data.summary.reserved)}</div>
              <div className="mt-0.5 text-[12px] leading-snug text-indigo-300/40">
                суммы активных заявок на вывод
              </div>
            </div>
            <div className="card-glass p-4">
              <div className="flex items-center gap-1.5 text-[12px] text-indigo-300/75">
                <Icon name="spark" className="h-3.5 w-3.5 text-emerald-glow" /> Ожидает оформления
              </div>
              <div className="mt-1 text-lg font-extrabold text-emerald-glow">
                {rub(data.summary.pending_setup)}
              </div>
              <div className="mt-0.5 text-[12px] leading-snug text-indigo-300/40">
                награды по незавершённым заявкам
              </div>
            </div>
          </section>

          <section className="mt-3 grid grid-cols-2 gap-3 px-5">
            <div className="card-glass p-4 text-center">
              <div className="text-lg font-extrabold text-emerald-glow">{rub(data.summary.paid_total)}</div>
              <div className="mt-1 text-[12px] text-indigo-300/75">всего выплачено</div>
            </div>
            <div className="card-glass p-4 text-center">
              <div className="text-lg font-extrabold text-gold-gradient">
                {rub(data.summary.referral_earned)}
              </div>
              <div className="mt-1 text-[12px] text-indigo-300/75">заработано на друзьях</div>
            </div>
          </section>

          <SectionTitle
            action={
              <Link to="/history" className="text-xs font-bold text-electric">
                Вся история
              </Link>
            }
          >
            Последние операции
          </SectionTitle>
          {data.entries.length === 0 ? (
            <p className="px-5 pb-6 text-sm text-indigo-300/75">
              Операций пока нет. Выполни первое предложение — начисление появится здесь.
            </p>
          ) : (
            <div className="space-y-2 px-5 pb-6">
              {data.entries.slice(0, 10).map((e) => (
                <div key={e.id} className="card-glass flex items-center justify-between gap-3 p-4">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">{e.kind_ru}</div>
                    <div className="truncate text-[12px] text-indigo-300/70">{e.note}</div>
                    <div className="text-[12px] text-indigo-300/40">{fmtDateTime(e.created)}</div>
                  </div>
                  <div
                    className={`shrink-0 text-sm font-extrabold ${
                      e.amount >= 0 ? "text-emerald-glow" : "text-rose-alert"
                    }`}
                  >
                    {e.amount >= 0 ? "+" : "−"}{rub(Math.abs(e.amount))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}