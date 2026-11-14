import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, rub } from "../lib/api";
import type { Dashboard } from "../lib/types";
import { useSession } from "../state/session";
import { Icon } from "../components/Icon";
import { OfferCard } from "../components/OfferCard";
import { ErrorState, ProgressBar, SectionTitle } from "../components/ui";
import { haptic } from "../lib/telegram";

export default function Home() {
  const { user } = useSession();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.get<Dashboard>("/dashboard"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <header className="safe-top flex items-center justify-between px-5 pb-2 pt-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-gold/40 bg-navy-900 shadow-glow-gold">
            <Icon name="crown" className="h-5 w-5 text-gold" />
          </div>
          <div>
            <div className="text-base font-extrabold tracking-[0.22em] text-gold-gradient">BONVERA</div>
            <div className="text-[10px] text-indigo-300/50">привет, {user?.name ?? "игрок"} 👋</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/notifications"
            className="relative flex h-10 w-10 items-center justify-center rounded-xl border border-royal/25 bg-navy-900/70 text-indigo-200"
            aria-label="Уведомления"
          >
            <Icon name="bell" className="h-5 w-5" />
            {data && data.unread_notifications > 0 && (
              <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-alert px-1 text-[9px] font-bold text-white">
                {data.unread_notifications}
              </span>
            )}
          </Link>
          <Link
            to="/profile"
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-royal/25 bg-navy-900/70 text-indigo-200"
            aria-label="Профиль"
          >
            <Icon name="profile" className="h-5 w-5" />
          </Link>
        </div>
      </header>

      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {!data && !error && (
        <div className="space-y-4 px-5 pt-3">
          <div className="skeleton h-44 w-full" />
          <div className="skeleton h-28 w-full" />
          <div className="skeleton h-40 w-full" />
        </div>
      )}

      {data && (
        <>
          <section className="px-5 pt-3">
            <div className="card-gold relative overflow-hidden p-5">
              <div className="absolute -right-8 -top-10 h-36 w-36 rounded-full bg-gold/10 blur-2xl" />
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-indigo-300/70">
                  Доступно к выводу
                </span>
                <Icon name="wallet" className="h-5 w-5 text-gold" />
              </div>
              <div className="mt-2 text-4xl font-extrabold text-gold-gradient">
                {rub(data.wallet.available)}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-2xl bg-navy-950/50 p-3">
                  <div className="text-[11px] text-indigo-300/60">Ожидает подтверждения</div>
                  <div className="mt-1 font-bold text-electric">
                    {rub(data.wallet.review + data.wallet.hold)}
                  </div>
                </div>
                <div className="rounded-2xl bg-navy-950/50 p-3">
                  <div className="text-[11px] text-indigo-300/60">Всего выплачено</div>
                  <div className="mt-1 font-bold text-emerald-glow">{rub(data.wallet.paid_total)}</div>
                </div>
              </div>
              <Link to="/withdraw" className="btn-gold mt-4 w-full" onClick={() => haptic("medium")}>
                <Icon name="arrow-up" className="h-4 w-4" /> Вывести
              </Link>
            </div>
          </section>

          <SectionTitle
            action={
              <Link to="/apps" className="text-xs font-bold text-electric">
                Мои заявки
              </Link>
            }
          >
            Твой прогресс
          </SectionTitle>
          <section className="px-5">
            <div className="card-glass space-y-4 p-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-royal/20 text-royal-soft">
                    <Icon name="chest" className="h-6 w-6" />
                  </div>
                  <div>
                    <div className="text-sm font-bold">Бонус за 10 заказов</div>
                    <div className="text-xs text-indigo-300/60">
                      {data.ten_progress}/10 подтверждённых · +500 ₽
                    </div>
                  </div>
                </div>
                <span className="text-lg font-extrabold text-gold-gradient">
                  {data.confirmed_orders}
                </span>
              </div>
              <ProgressBar value={data.ten_progress} max={10} gold />
              <div className="grid grid-cols-2 gap-3 pt-1 text-center">
                <Link to="/tasks" className="rounded-2xl bg-navy-950/50 p-3">
                  <div className="text-lg font-extrabold text-electric">
                    {data.tasks_done}/{data.tasks_total}
                  </div>
                  <div className="text-[11px] text-indigo-300/60">заданий выполнено</div>
                </Link>
                <Link to="/friends" className="rounded-2xl bg-navy-950/50 p-3">
                  <div className="text-lg font-extrabold text-emerald-glow">
                    {data.referral.qualified}
                  </div>
                  <div className="text-[11px] text-indigo-300/60">друзей с выплатой</div>
                </Link>
              </div>
            </div>
          </section>

          <SectionTitle
            action={
              <Link to="/catalog" className="text-xs font-bold text-electric">
                Весь каталог
              </Link>
            }
          >
            Популярные предложения
          </SectionTitle>
          <section className="grid grid-cols-2 gap-3 px-5">
            {data.popular_offers.slice(0, 4).map((o) => (
              <OfferCard key={o.id} offer={o} compact />
            ))}
          </section>
          {data.popular_offers.length === 0 && (
            <p className="px-5 text-sm text-indigo-300/60">Каталог обновляется — загляни позже.</p>
          )}

          <SectionTitle
            action={
              <Link to="/achievements" className="text-xs font-bold text-electric">
                Все
              </Link>
            }
          >
            Бонусные достижения
          </SectionTitle>
          <section className="grid grid-cols-2 gap-3 px-5 pb-6">
            {data.achievements_preview.map((a) => (
              <div
                key={a.key}
                className={`card-glass flex flex-col items-center gap-2 p-4 text-center ${
                  a.unlocked ? "border-gold/40" : "opacity-80"
                }`}
              >
                <div
                  className={`flex h-12 w-12 items-center justify-center rounded-2xl ${
                    a.unlocked ? "bg-gold/15 text-gold shadow-glow-gold" : "bg-navy-800 text-indigo-300/50"
                  }`}
                >
                  <Icon name={a.icon as never} className="h-6 w-6" />
                </div>
                <div className="text-xs font-bold leading-tight">{a.title}</div>
                <div className={`text-[10px] font-bold ${a.unlocked ? "text-emerald-glow" : "text-indigo-300/50"}`}>
                  {a.unlocked ? "Получено" : "Впереди"}
                </div>
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  );
}