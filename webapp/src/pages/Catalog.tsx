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
  { key: "rko", label: "РКО" },
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
    if (category === "rko") return null;
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
      <PageHeader title="Каталог" subtitle="Выбирай предложение и получай вознаграждение" back="/" />

      <section className="px-5 pb-4 pt-1">
        <div className="relative overflow-hidden rounded-3xl border border-electric/15 bg-gradient-to-br from-[#142544] via-[#101a36] to-[#0a1124] p-4 shadow-card">
          <div className="pointer-events-none absolute -right-8 -top-10 h-36 w-36 rounded-full bg-electric/10 blur-3xl" />
          <div className="relative flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-electric/20 bg-electric/10 text-electric">
              <Icon name="spark" className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-extrabold text-white">Твой следующий бонус начинается здесь</h2>
              <p className="mt-1 text-[11px] leading-relaxed text-indigo-200/70">
                Сравни вознаграждение и условия. Перед оформлением покажем, что нужно сделать и какие подтверждения понадобятся.
              </p>
            </div>
          </div>
          {data && category !== "rko" && (
            <div className="relative mt-3 flex items-center justify-between border-t border-white/[0.08] pt-3 text-[11px]">
              <span className="text-indigo-200/65">Предложений в подборке</span>
              <span className="font-extrabold text-electric">{data.length}</span>
            </div>
          )}
        </div>
      </section>

      <div className="space-y-3 px-5">
        {category !== "rko" && (
        <div className="relative">
          <Icon name="search" className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-indigo-300/70" />
          <input
            className="input-dark pl-11"
            placeholder="Поиск по банку или названию…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Поиск предложений"
          />
          {q && (
            <button
              type="button"
              onClick={() => setQ("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg px-2 py-1 text-[11px] font-bold text-electric"
              aria-label="Очистить поиск"
            >
              Очистить
            </button>
          )}
        </div>

        )}

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

        {category !== "rko" && (
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
        )}
      </div>

      {category === "rko" ? (
        <section className="px-5 pt-2" aria-labelledby="rko-title">
          <div className="relative overflow-hidden rounded-3xl border border-gold/25 bg-gradient-to-br from-[#17172f] via-[#11172d] to-[#101c2c] p-5 shadow-card">
            <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-gold/10 blur-3xl" />
            <div className="relative flex items-start justify-between gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-gold/25 bg-gold/10 text-gold shadow-glow-gold">
                <Icon name="wallet" className="h-6 w-6" />
              </div>
              <span className="rounded-full border border-gold/25 bg-gold/10 px-3 py-1 text-[11px] font-bold text-gold">Скоро</span>
            </div>
            <div className="relative mt-5">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-gold/80">Для бизнеса</p>
              <h2 id="rko-title" className="mt-2 text-2xl font-extrabold tracking-tight text-white">Расчётный счёт и РКО</h2>
              <p className="mt-2 max-w-sm text-sm leading-relaxed text-indigo-200/75">Подбор предложений для открытия расчётного счёта, регистрации бизнеса и обслуживания ИП и ООО.</p>
            </div>
            <div className="relative mt-5 grid grid-cols-2 gap-2">
              <div className="rounded-2xl border border-white/5 bg-black/20 p-3">
                <div className="text-xs font-bold text-indigo-100">ИП и ООО</div>
                <div className="mt-1 text-[11px] text-indigo-300/65">Предложения для бизнеса</div>
              </div>
              <div className="rounded-2xl border border-white/5 bg-black/20 p-3">
                <div className="text-xs font-bold text-indigo-100">Бонусы за оформление</div>
                <div className="mt-1 text-[11px] text-indigo-300/65">Размеры появятся с офферами</div>
              </div>
            </div>
            <p className="relative mt-4 text-[11px] leading-relaxed text-indigo-300/60">Категория уже добавлена в каталог. Предложения и условия появятся после проверки партнёрских офферов.</p>
          </div>
        </section>
      ) : (
      <div className="pt-4">
        {data && data.length > 0 && (
          <div className="flex items-center justify-between px-5 pb-3 text-[11px]">
            <span className="text-indigo-300/65">
              {category === "all" ? "Все предложения" : CATEGORIES.find((item) => item.key === category)?.label}
            </span>
            <span className="font-semibold text-indigo-100">{data.length} шт.</span>
          </div>
        )}
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
      )}
    </div>
  );
}