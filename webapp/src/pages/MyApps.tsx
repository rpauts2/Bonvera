import { useState } from "react";
import { Link } from "react-router-dom";
import { useLoad } from "../lib/useLoad";
import { fmtDate, rub } from "../lib/api";
import type { MyApp } from "../lib/types";
import { Icon } from "../components/Icon";
import { EmptyState, ErrorState, ListSkeleton, PageHeader, StatusBadge } from "../components/ui";
import { haptic } from "../lib/telegram";

const FILTERS = [
  { key: "all", label: "Все" },
  { key: "active", label: "Активные" },
  { key: "confirmed", label: "Подтверждённые" },
  { key: "paid", label: "Выплаченные" },
  { key: "closed", label: "Отклонённые" },
] as const;

function matches(a: MyApp, f: string): boolean {
  if (f === "all") return true;
  if (f === "active") return a.status === "new" || a.status === "proof" || a.status === "hold";
  if (f === "confirmed") return a.status === "confirmed";
  if (f === "paid") return a.status === "paid";
  return a.status === "rejected" || a.status === "expired";
}

function nextStep(a: MyApp): { text: string; tone: string } | null {
  switch (a.status) {
    case "new":
      return a.submitted ? { text: "Ждём проверки", tone: "text-indigo-300/70" } : { text: "Загрузи подтверждение", tone: "text-electric" };
    case "proof":
      return { text: "Проверяем доказательства", tone: "text-indigo-300/70" };
    case "hold":
      return { text: "Ждём подтверждения сети", tone: "text-gold" };
    case "confirmed":
      return { text: "Можно выводить на карту", tone: "text-emerald-glow" };
    case "paid":
      return { text: "Выплачено", tone: "text-emerald-glow" };
    case "rejected":
      return { text: "Отказ, причина внутри", tone: "text-rose-300" };
    case "expired":
      return { text: "Бронь истекла, можно взять заново", tone: "text-indigo-300/70" };
    default:
      return null;
  }
}

export default function MyApps() {
  const { data, error, reload } = useLoad<MyApp[]>("/apps");
  const [filter, setFilter] = useState<string>("all");

  const visible = data?.filter((a) => matches(a, filter)) ?? [];

  return (
    <div>
      <PageHeader
        title="Мои заявки"
        back="/profile"
        right={
          <Link to="/catalog" className="btn-ghost px-3 py-2 text-xs" onClick={() => haptic("light")}>
            <Icon name="plus" className="h-4 w-4" /> Новая
          </Link>
        }
      />

      <div className="no-scrollbar -mx-0 flex gap-2 overflow-x-auto px-5 pb-3">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => {
              haptic("light");
              setFilter(f.key);
            }}
            className={`shrink-0 rounded-full border px-4 py-2 text-xs font-bold transition-colors ${
              filter === f.key
                ? "border-electric/50 bg-electric/15 text-electric"
                : "border-royal/25 bg-navy-900/70 text-indigo-300/70"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!data && !error && <ListSkeleton rows={3} />}
      {data && visible.length === 0 && (
        <EmptyState
          icon="doc"
          title={filter === "all" ? "Заявок пока нет" : "В этой категории пусто"}
          text="Выбери предложение в каталоге, выполни условие и загрузи подтверждение — заявка появится здесь."
        />
      )}
      {data && visible.length > 0 && (
        <div className="space-y-3 px-5 pb-6">
          {visible.map((a) => (
            <Link
              key={a.id}
              to={`/apps/${a.id}`}
              onClick={() => haptic("light")}
              className="card-glass block p-4 transition-transform active:scale-[0.99]"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-navy-800 text-xl">
                  {a.image_url ? (
                    <img src={a.image_url} alt="" className="h-full w-full object-cover" loading="lazy" />
                  ) : (
                    <span>{a.emoji}</span>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12px] font-semibold uppercase tracking-wide text-indigo-300/70">
                    {a.brand}
                  </div>
                  <div className="truncate text-sm font-bold">{a.offer_name}</div>
                  <div className="mt-0.5 text-[12px] text-indigo-300/45">от {fmtDate(a.created)}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-sm font-extrabold text-gold-gradient">{rub(a.cashback || a.reward)}</div>
                  <Icon name="chevron-right" className="ml-auto mt-1 h-4 w-4 text-indigo-300/40" />
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusBadge status={a.status} />
                {a.status === "hold" && a.hold_until && (
                  <span className="text-[12px] text-indigo-300/70">холд до {fmtDate(a.hold_until)}</span>
                )}
                {a.status !== "hold" && (() => {
                  const step = nextStep(a);
                  return step ? <span className={`text-[12px] font-semibold ${step.tone}`}>{step.text}</span> : null;
                })()}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}