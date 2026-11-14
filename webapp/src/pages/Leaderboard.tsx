import { useMemo, useState } from "react";
import { useLoad } from "../lib/useLoad";
import type { Leaderboard as LeaderboardData } from "../lib/types";
import { Icon } from "../components/Icon";
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from "../components/ui";
import { haptic } from "../lib/telegram";

const RANK_CLS: Record<number, string> = {
  1: "bg-gold/15 text-gold border-gold/40 shadow-glow-gold",
  2: "bg-indigo-300/10 text-indigo-200 border-indigo-300/30",
  3: "bg-amber-glow/10 text-amber-glow border-amber-glow/30",
};

export default function Leaderboard() {
  const [type, setType] = useState<"orders" | "friends">("orders");
  const [period, setPeriod] = useState<"month" | "all">("month");

  const path = useMemo(() => `/leaderboard?type=${type}&period=${period}`, [type, period]);
  const { data, error, loading, reload } = useLoad<LeaderboardData>(path);

  const unit = type === "orders" ? "зак." : "друзей";

  return (
    <div>
      <PageHeader title="Рейтинг" subtitle="Только реальные результаты" back="/profile" />

      <div className="space-y-3 px-5">
        <div className="grid grid-cols-2 gap-2">
          {(
            [
              { key: "orders", label: "Заказы", icon: "doc" },
              { key: "friends", label: "Друзья", icon: "friends" },
            ] as const
          ).map((t) => (
            <button
              key={t.key}
              onClick={() => {
                haptic("light");
                setType(t.key);
              }}
              className={`flex items-center justify-center gap-2 rounded-2xl border px-4 py-3 text-sm font-bold transition-colors ${
                type === t.key
                  ? "border-electric/50 bg-electric/15 text-electric shadow-glow-electric"
                  : "border-royal/25 bg-navy-900/70 text-indigo-300/70"
              }`}
            >
              <Icon name={t.icon} className="h-4 w-4" /> {t.label}
            </button>
          ))}
        </div>
        <div className="flex justify-center gap-2">
          {(
            [
              { key: "month", label: "За месяц" },
              { key: "all", label: "Всё время" },
            ] as const
          ).map((p) => (
            <button
              key={p.key}
              onClick={() => {
                haptic("light");
                setPeriod(p.key);
              }}
              className={`rounded-full border px-4 py-1.5 text-xs font-bold ${
                period === p.key
                  ? "border-gold/40 bg-gold/10 text-gold"
                  : "border-royal/25 bg-navy-900/70 text-indigo-300/75"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="pt-4">
        {error && <ErrorState message={error} onRetry={() => void reload()} />}
        {loading && !data && <ListSkeleton rows={4} />}
        {data && (
          <>
            <section className="px-5">
              <div className="card-gold flex items-center justify-between p-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gold/15 text-gold">
                    <Icon name="trophy" className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-xs text-indigo-300/75">Твоё место</div>
                    <div className="text-lg font-extrabold text-gold-gradient">
                      {data.me.rank != null ? `#${data.me.rank}` : "—"}
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-lg font-extrabold text-electric">{data.me.value}</div>
                  <div className="text-[12px] text-indigo-300/75">{unit}</div>
                </div>
              </div>
            </section>

            {data.rows.length === 0 ? (
              <div className="pt-3">
                <EmptyState
                  icon="trophy"
                  title="Пока нет участников"
                  text="Рейтинг строится только по реальным подтверждённым заказам и друзьям с выплатой. Стань первым!"
                />
              </div>
            ) : (
              <section className="space-y-2 px-5 pt-3">
                {data.rows.map((r) => (
                  <div
                    key={`${r.rank}-${r.display}`}
                    className={`card-glass flex items-center gap-3 p-3.5 ${
                      r.is_me ? "border-electric/45 shadow-glow-electric" : ""
                    }`}
                  >
                    <span
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border text-sm font-extrabold ${
                        RANK_CLS[r.rank] ?? "border-royal/25 bg-navy-800 text-indigo-300/70"
                      }`}
                    >
                      {r.rank}
                    </span>
                    <div className="min-w-0 flex-1 truncate text-sm font-bold">
                      {r.display}
                      {r.is_me && <span className="ml-2 text-[12px] font-bold text-electric">это ты</span>}
                    </div>
                    <div className="shrink-0 text-sm font-extrabold text-gold-gradient">
                      {r.value} <span className="text-[12px] font-semibold text-indigo-300/70">{unit}</span>
                    </div>
                  </div>
                ))}
              </section>
            )}
            <p className="px-5 pb-6 pt-4 text-[12px] leading-relaxed text-indigo-300/70">
              В рейтинге показываются только никнеймы или обезличенные имена. Telegram ID, телефоны и
              другие личные данные не публикуются. Накрутка приводит к блокировке.
            </p>
          </>
        )}
      </div>
    </div>
  );
}