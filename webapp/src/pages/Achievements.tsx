import { useLoad } from "../lib/useLoad";
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
          <div className="grid grid-cols-2 gap-3 px-5 pb-4">
            {data.map((a) => (
              <div
                key={a.key}
                className={`card-glass relative flex flex-col items-center gap-2 p-5 text-center ${
                  a.unlocked ? "border-gold/40" : "opacity-75"
                }`}
              >
                <div
                  className={`relative flex h-14 w-14 items-center justify-center rounded-2xl ${
                    a.unlocked ? "bg-gold/15 text-gold shadow-glow-gold" : "bg-navy-800 text-indigo-300/45"
                  }`}
                >
                  <Icon name={(a.icon as IconName) ?? "star"} className="h-7 w-7" />
                  {!a.unlocked && (
                    <span className="absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-navy-950 text-indigo-300/60">
                      <Icon name="lock" className="h-3 w-3" />
                    </span>
                  )}
                </div>
                <div className="text-xs font-bold leading-tight">{a.title}</div>
                <p className="text-[10px] leading-relaxed text-indigo-300/55">{a.description}</p>
                <div
                  className={`text-[10px] font-bold ${
                    a.unlocked ? "text-emerald-glow" : "text-indigo-300/45"
                  }`}
                >
                  {a.unlocked ? `Получено ${fmtDate(a.unlocked_at)}` : "Впереди"}
                </div>
              </div>
            ))}
          </div>
          <p className="px-5 pb-6 text-[11px] leading-relaxed text-indigo-300/50">
            Достижения отражают реальные подтверждённые действия: заказы, выплаты и приглашённых друзей.
            Никаких ежедневных заданий и искусственных счётчиков.
          </p>
        </>
      )}
    </div>
  );
}