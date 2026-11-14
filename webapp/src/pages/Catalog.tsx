import { useEffect, useMemo, useState } from "react";
import { useLoad } from "../lib/useLoad";
import type { OfferCard as OfferCardType } from "../lib/types";
import { OfferCard } from "../components/OfferCard";
import { Icon } from "../components/Icon";
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from "../components/ui";
import { haptic } from "../lib/telegram";

const CATEGORIES = [
  { key: "all", label: "Все" },
  { key: "cards", label: "Карты" },
  { key: "bk", label: "Букмекеры" },
  { key: "mfo", label: "Займы МФО" },
  { key: "cpl", label: "CPL-заявки" },
] as const;

const SORTS = [
  { key: "reward", label: "По награде" },
  { key: "hold", label: "Быстрый холд" },
  { key: "new", label: "Сначала новые" },
] as const;

export default function Catalog() {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [sort, setSort] = useState<string>("reward");
  const [availableOnly, setAvailableOnly] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const path = useMemo(() => {
    const params = new URLSearchParams();
    if (debouncedQ) params.set("q", debouncedQ);
    if (category !== "all") params.set("category", category);
    params.set("sort", sort);
    if (availableOnly) params.set("available", "1");
    return `/offers?${params.toString()}`;
  }, [debouncedQ, category, sort, availableOnly]);

  const { data, error, loading, reload } = useLoad<OfferCardType[]>(path);

  return (
    <div>
      <PageHeader title="Каталог" subtitle="Карты · Букмекеры · МФО · CPL" back="/" />

      <div className="space-y-3 px-5">
        <div className="relative">
          <Icon name="search" className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-indigo-300/70" />
          <input
            className="input-dark pl-11"
            placeholder="Поиск по банку или названию…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Поиск предложений"
          />
        </div>

        <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 pb-1">
          {CATEGORIES.map((c) => (
            <button
              key={c.key}
              onClick={() => {
                haptic("light");
                setCategory(c.key);
              }}
              className={`shrink-0 rounded-full border px-4 py-2 text-xs font-bold transition-colors ${
                category === c.key
                  ? "border-electric/50 bg-electric/15 text-electric shadow-glow-electric"
                  : "border-royal/25 bg-navy-900/70 text-indigo-300/70"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <select
            className="input-dark flex-1 appearance-none py-2.5 text-sm"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            aria-label="Сортировка"
          >
            {SORTS.map((s) => (
              <option key={s.key} value={s.key} className="bg-navy-900">
                {s.label}
              </option>
            ))}
          </select>
          <button
            onClick={() => {
              haptic("light");
              setAvailableOnly((v) => !v);
            }}
            className={`flex shrink-0 items-center gap-1.5 rounded-2xl border px-3.5 py-2.5 text-xs font-bold ${
              availableOnly
                ? "border-emerald-glow/50 bg-emerald-glow/15 text-emerald-glow"
                : "border-royal/25 bg-navy-900/70 text-indigo-300/70"
            }`}
            aria-pressed={availableOnly}
          >
            <Icon name="check" className="h-3.5 w-3.5" /> Доступные
          </button>
        </div>
      </div>

      <div className="pt-4">
        {error && <ErrorState message={error} onRetry={() => void reload()} />}
        {loading && !data && <ListSkeleton rows={4} />}
        {data && data.length === 0 && (
          <EmptyState
            icon="search"
            title="Ничего не найдено"
            text="Попробуй изменить запрос или фильтры. Новые предложения появляются после проверки условий."
          />
        )}
        {data && data.length > 0 && (
          <>
            <div className="grid grid-cols-2 gap-3 px-5 sm:grid-cols-3 xl:grid-cols-4">
              {data.map((o) => (
                <OfferCard key={o.id} offer={o} />
              ))}
            </div>
            <p className="px-5 pb-6 pt-4 text-[12px] leading-relaxed text-indigo-300/70">
              Предложения без партнёрской ссылки показаны, но оформить их нельзя, пока администратор не
              добавит проверенную ссылку. Мы не выдумываем ссылки и условия.
            </p>
          </>
        )}
      </div>
    </div>
  );
}