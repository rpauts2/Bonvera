import { useLoad } from "../lib/useLoad";
import { Link } from "react-router-dom";
import { fmtDate } from "../lib/api";
import type { Achievement } from "../lib/types";
import { Icon, type IconName } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader } from "../components/ui";

export default function Achievements() {
  const { data, error, reload } = useLoad<Achievement[]>("/achievements");

  return (
    <div>
      <PageHeader title="Достижения" subtitle="Вехи за реальные действия" back="/profile" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!data && !error && <ListSkeleton rows={3} />}
      {data && (
        <>
          <section className="px-5 pb-4">
            <div className="relative overflow-hidden rounded-3xl border border-gold/20 bg-gradient-to-br from-[#282044] via-[#171b38] to-[#0b1227] p-4">
              <div className="pointer-events-none absolute -right-7 -top-8 h-28 w-28 rounded-full bg-gold/10 blur-3xl" />
              <div className="relative flex items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold/70">Твои достижения</div>
                  <div className="mt-1 text-2xl font-black text-white">{data.filter((a) => a.unlocked).length}<span className="ml-1 text-sm font-semibold text-indigo-200/55">/ {data.length}</span></div>
                  <p className="mt-1 text-[11px] text-indigo-200/65">Открываются за подтверждённые действия</p>
                </div>
                <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-gold/20 bg-gold/10 text-gold shadow-glow-gold">
                  <Icon name="trophy" className="h-7 w-7" />
                </div>
              </div>
              <div className="relative mt-3 h-2 overflow-hidden rounded-full bg-navy-950/70">
                <div className="h-full rounded-full bg-gradient-to-r from-amber-glow to-gold transition-all duration-700" style={{ width: `${data.length ? (data.filter((a) => a.unlocked).length / data.length) * 100 : 0}%` }} />
              </div>
            </div>
          </section>
          <div className="grid grid-cols-2 gap-3 px-5 pb-4">
            {data.map((a) => (
              <div
                key={a.key}
                className={`card-glass relative flex flex-col items-center gap-2 p-5 text-center ${
                  a.unlocked ? "border-gold/35 bg-gradient-to-b from-gold/[0.06] to-transparent" : "opacity-70"
                }`}
              >
                <div
                  className={`relative flex h-14 w-14 items-center justify-center rounded-2xl ${
                    a.unlocked ? "bg-gold/15 text-gold shadow-glow-gold" : "bg-navy-800 text-indigo-300/45"
                  }`}
                >
                  <Icon name={(a.icon as IconName) ?? "star"} className="h-7 w-7" />
                  {!a.unlocked && (
                    <span className="absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-navy-950 text-indigo-300/75">
                      <Icon name="lock" className="h-3 w-3" />
                    </span>
                  )}
                </div>
                <div className="text-xs font-bold leading-tight">{a.title}</div>
                <p className="text-[12px] leading-relaxed text-indigo-300/70">{a.description}</p>
                <div
                  className={`text-[12px] font-bold ${
                    a.unlocked ? "text-emerald-glow" : "text-indigo-300/45"
                  }`}
                >
                  {a.unlocked ? `Получено ${fmtDate(a.unlocked_at)}` : "Впереди"}
                </div>
              </div>
            ))}
          </div>
          <section className="space-y-3 px-5 pb-6">
            <p className="text-[11px] leading-relaxed text-indigo-300/65">
              Достижения отражают реальные подтверждённые действия: заказы, выплаты и приглашённых друзей. Никаких ежедневных заданий и искусственных счётчиков.
            </p>
            <Link to="/catalog" className="btn-primary w-full">
              <Icon name="catalog" className="h-4 w-4" /> Перейти к предложениям
            </Link>
          </section>
        </>
      )}
    </div>
  );
}