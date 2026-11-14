import { useState } from "react";
import { useLoad } from "../lib/useLoad";
import { fmtDateTime, rub } from "../lib/api";
import type { WalletEntry } from "../lib/types";
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from "../components/ui";
import { haptic } from "../lib/telegram";

const FILTERS = [
  { key: "all", label: "Все" },
  { key: "in", label: "Начисления" },
  { key: "out", label: "Списания" },
  { key: "bonus", label: "Бонусы" },
  { key: "ref", label: "Реферальные" },
] as const;

function matches(e: WalletEntry, f: string): boolean {
  if (f === "all") return true;
  if (f === "in") return e.amount > 0;
  if (f === "out") return e.amount < 0;
  if (f === "bonus") return e.kind.startsWith("task");
  return e.kind.startsWith("ref");
}

export default function History() {
  const { data, error, reload } = useLoad<WalletEntry[]>("/wallet/entries");
  const [filter, setFilter] = useState<string>("all");

  const visible = data?.filter((e) => matches(e, filter)) ?? [];

  return (
    <div>
      <PageHeader title="История операций" subtitle="Каждая операция — запись в кошельке" back="/wallet" />

      <div className="no-scrollbar flex gap-2 overflow-x-auto px-5 pb-3">
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
      {!data && !error && <ListSkeleton rows={5} />}
      {data && visible.length === 0 && (
        <EmptyState
          icon="clock"
          title="Операций нет"
          text="Здесь появятся все начисления за заказы, бонусы, реферальные комиссии и выводы."
        />
      )}
      {data && visible.length > 0 && (
        <div className="space-y-2 px-5 pb-6">
          {visible.map((e) => (
            <div key={e.id} className="card-glass flex items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <div className="truncate text-sm font-bold">{e.kind_ru}</div>
                <div className="truncate text-[11px] text-indigo-300/50">{e.note}</div>
                <div className="text-[10px] text-indigo-300/40">{fmtDateTime(e.created)}</div>
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
    </div>
  );
}