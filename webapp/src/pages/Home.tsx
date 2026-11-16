import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDateTime, rub } from "../lib/api";
import type { Dashboard } from "../lib/types";
import { useSession } from "../state/session";
import { Icon } from "../components/Icon";
import { OfferCard } from "../components/OfferCard";
import { ErrorState, ProgressBar, SectionTitle } from "../components/ui";
import { haptic, hapticNotify, openExternal, showAlert } from "../lib/telegram";

/**
 * The home screen.
 *
 * `initialData` allows the screen to be rendered with an already loaded
 * dashboard (server-side rendering and tests). In the app the data always
 * comes from `/api/v1/dashboard`.
 */
export default function Home({ initialData }: { initialData?: Dashboard } = {}) {
  const { user } = useSession();
  const [data, setData] = useState<Dashboard | null>(initialData ?? null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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

  async function copyRef() {
    if (!data?.ref_link) return;
    try {
      await navigator.clipboard.writeText(data.ref_link);
      setCopied(true);
      hapticNotify("success");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      showAlert("Скопируй ссылку вручную: " + data.ref_link);
    }
  }

  const wallet = data?.wallet;
  const available = wallet?.available ?? 0;
  const minWithdraw = wallet?.min_withdraw ?? 300;
  const canWithdraw = available >= minWithdraw;
  const pending = (wallet?.review ?? 0) + (wallet?.hold ?? 0);
  const hasActivity = pending > 0 || (wallet?.paid_total ?? 0) > 0;

  const nextGoal = data?.achievements_preview?.find((a) => !a.unlocked);
  const topEvents = data?.recent_events ?? [];

  return (
    <div>
      <header className="safe-top flex items-center justify-between px-5 pb-2 pt-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-gold/40 bg-navy-900 shadow-glow-gold">
            <Icon name="crown" className="h-5 w-5 text-gold" />
          </div>
          <div>
            <div className="text-base font-extrabold tracking-[0.22em] text-gold-gradient">BONVERA</div>
            <div className="text-[12px] text-indigo-300/70">привет, {user?.name ?? "игрок"} 👋</div>
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
              <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-alert px-1 text-[12px] font-bold text-white">
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
          {/* Финансовая карточка */}
          <section className="px-5 pt-3">
            <div className="card-gold relative overflow-hidden p-5">
              <div className="absolute -right-8 -top-10 h-36 w-36 rounded-full bg-gold/10 blur-2xl" />
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-semibold uppercase tracking-wider text-indigo-300/70">
                  Доступно к выводу
                </span>
                <Icon name="wallet" className="h-5 w-5 text-gold" />
              </div>
              <div className="mt-2 text-4xl font-extrabold text-gold-gradient">{rub(available)}</div>

              {hasActivity ? (
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-2xl bg-navy-950/50 p-3">
                    <div className="text-[12px] text-indigo-300/70">Ожидает подтверждения</div>
                    <div className="mt-1 font-bold text-electric">{rub(pending)}</div>
                  </div>
                  <div className="rounded-2xl bg-navy-950/50 p-3">
                    <div className="text-[12px] text-indigo-300/70">Всего выплачено</div>
                    <div className="mt-1 font-bold text-emerald-glow">{rub(wallet?.paid_total ?? 0)}</div>
                  </div>
                </div>
              ) : (
                <p className="mt-3 text-[12px] leading-relaxed text-indigo-300/70">
                  Пока нет активных заявок и выплат. Оформи предложение — награда придёт после проверки.
                </p>
              )}

              {canWithdraw ? (
                <Link to="/withdraw" className="btn-gold mt-4 w-full" onClick={() => haptic("medium")}>
                  <Icon name="arrow-up" className="h-4 w-4" /> Вывести
                </Link>
              ) : (
                <>
                  <Link to="/catalog" className="btn-gold mt-4 w-full" onClick={() => haptic("medium")}>
                    <Icon name="catalog" className="h-4 w-4" /> Как заработать
                  </Link>
                  <p className="mt-2 text-center text-[12px] text-indigo-300/70">
                    Минимум вывода — {rub(minWithdraw)}. Выплаты делаем вручную по СБП после проверки
                    администратором.
                  </p>
                </>
              )}
            </div>
          </section>

          {/* Прогресс */}
          <SectionTitle
            action={
              <Link to="/apps" className="text-[12px] font-bold text-electric">
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
                    <div className="text-[12px] text-indigo-300/70">
                      {data.ten_progress}/10 подтверждённых · +500 ₽
                    </div>
                  </div>
                </div>
                <span className="text-lg font-extrabold text-gold-gradient">{data.confirmed_orders}</span>
              </div>
              <ProgressBar value={data.ten_progress} max={10} gold />
              {data.confirmed_orders === 0 && (
                <Link
                  to="/catalog"
                  className="flex items-center justify-between rounded-2xl bg-navy-950/50 p-3 text-[13px] font-semibold text-electric"
                >
                  Оформи первое предложение и получи +10 ₽
                  <Icon name="chevron-right" className="h-4 w-4" />
                </Link>
              )}
              <div className="grid grid-cols-2 gap-3 pt-1 text-center">
                <Link to="/tasks" className="rounded-2xl bg-navy-950/50 p-3">
                  <div className="text-lg font-extrabold text-electric">
                    {data.tasks_done}/{data.tasks_total}
                  </div>
                  <div className="text-[12px] text-indigo-300/70">заданий выполнено</div>
                </Link>
                <Link to="/friends" className="rounded-2xl bg-navy-950/50 p-3">
                  <div className="text-lg font-extrabold text-emerald-glow">
                    {data.referral.qualified}
                  </div>
                  <div className="text-[12px] text-indigo-300/70">друзей с выплатой</div>
                </Link>
              </div>
            </div>
          </section>

          {/* Популярные предложения */}
          <SectionTitle
            action={
              <Link to="/catalog" className="text-[12px] font-bold text-electric">
                Весь каталог
              </Link>
            }
          >
            Популярные предложения
          </SectionTitle>
          {data.popular_offers.length === 0 ? (
            <div className="px-5">
              <div className="card-glass p-5 text-[13px] leading-relaxed text-indigo-200/75">
                <p className="font-bold text-indigo-100">Каталог обновляется</p>
                <p className="mt-1">
                  Часть предложений ждёт проверки партнёрской ссылки — мы не выдумываем ссылки и не
                  обещаем выплаты без подтверждённой сети.
                </p>
                <Link to="/catalog" className="btn-ghost mt-4 w-full">
                  <Icon name="catalog" className="h-4 w-4" /> Открыть каталог
                </Link>
              </div>
            </div>
          ) : (
            <section className="grid grid-cols-2 gap-3 px-5 sm:grid-cols-3 xl:grid-cols-4">
              {data.popular_offers.map((o) => (
                <OfferCard key={o.id} offer={o} compact />
              ))}
            </section>
          )}

          {/* Приглашение друга — главный канал роста */}
          <section className="px-5 pt-4">
            <div className="card-gold flex flex-col gap-3 p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gold/15 text-gold">
                  <Icon name="gift" className="h-6 w-6" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-extrabold text-gold-gradient">+100 ₽ за друга</div>
                  <div className="text-[12px] text-indigo-300/70">
                    Друг получит первую выплату — получишь бонус
                  </div>
                </div>
              </div>
              <div className="rounded-2xl bg-navy-950/60 p-3">
                <div className="break-all text-[12px] leading-relaxed text-electric">{data.ref_link}</div>
              </div>
              <div className="flex gap-2">
                <button className="btn-ghost flex-1" onClick={() => void copyRef()}>
                  <Icon name={copied ? "check" : "copy"} className="h-4 w-4" />
                  {copied ? "Скопировано" : "Копировать"}
                </button>
                <Link to="/friends" className="btn-gold flex-1">
                  <Icon name="friends" className="h-4 w-4" /> Друзья
                </Link>
              </div>
            </div>
          </section>

          {/* Канал */}
          {data.channel_url && (
            <section className="px-5 pt-4">
              <button
                className="card-glass flex w-full items-center justify-between gap-3 p-4 text-left"
                onClick={() => {
                  haptic("light");
                  openExternal(data.channel_url!);
                }}
              >
                <span className="flex items-center gap-3">
                  <Icon name="bell" className="h-5 w-5 text-electric" />
                  <span>
                    <span className="block text-sm font-bold">Подпишись на канал BONVERA</span>
                    <span className="block text-[12px] text-indigo-300/70">
                      +20 ₽ за подтверждённую подписку
                    </span>
                  </span>
                </span>
                <Icon name="chevron-right" className="h-5 w-5 text-indigo-300/70" />
              </button>
            </section>
          )}

          {/* Последние события */}
          {topEvents.length > 0 && (
            <>
              <SectionTitle
                action={
                  <Link to="/notifications" className="text-[12px] font-bold text-electric">
                    Все
                  </Link>
                }
              >
                Последние события
              </SectionTitle>
              <section className="space-y-2 px-5">
                {topEvents.map((e) => (
                  <div key={e.id} className="card-glass flex items-start gap-3 p-4">
                    <Icon
                      name={e.kind === "payout" ? "wallet" : e.kind === "bonus" ? "gift" : "doc"}
                      className="mt-0.5 h-4 w-4 shrink-0 text-electric"
                    />
                    <div className="min-w-0">
                      <div className="text-[13px] font-bold">{e.title}</div>
                      <div className="text-[12px] leading-relaxed text-indigo-300/70">{e.text}</div>
                      <div className="text-[12px] text-indigo-300/50">{fmtDateTime(e.created)}</div>
                    </div>
                  </div>
                ))}
              </section>
            </>
          )}

          {/* Следующая цель */}
          <SectionTitle
            action={
              <Link to="/achievements" className="text-[12px] font-bold text-electric">
                Все
              </Link>
            }
          >
            Ближайшая цель
          </SectionTitle>
          <section className="px-5 pb-6">
            {nextGoal ? (
              <div className="card-glass flex items-center gap-4 p-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-navy-800 text-indigo-300/70">
                  <Icon name={nextGoal.icon as never} className="h-6 w-6" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-bold">{nextGoal.title}</div>
                  <div className="text-[12px] leading-relaxed text-indigo-300/70">{nextGoal.description}</div>
                </div>
                <Icon name="chevron-right" className="h-5 w-5 shrink-0 text-indigo-300/50" />
              </div>
            ) : (
              <div className="card-glass flex items-center gap-3 p-4 text-[13px] font-semibold text-emerald-glow">
                <Icon name="check" className="h-5 w-5" /> Все достижения получены
              </div>
            )}
          </section>

          {/* Доверие */}
          <section className="px-5 pb-6">
            <Link
              to="/rules"
              className="card-glass flex items-start gap-2.5 p-4 text-[12px] leading-relaxed text-indigo-200/70"
            >
              <Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
              <span>
                Награды начисляются только после проверки выполненных условий. Выплаты — ручной
                перевод по СБП, займы и ставки не являются способом заработка.
              </span>
            </Link>
          </section>
        </>
      )}
    </div>
  );
}
