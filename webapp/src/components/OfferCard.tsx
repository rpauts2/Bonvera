import { Link } from "react-router-dom";
import type { OfferCard as OfferCardType } from "../lib/types";
import { Icon } from "./Icon";
import { haptic } from "../lib/telegram";

const CAT_LABEL: Record<string, string> = {
  cards: "Карты",
  bk: "Букмекеры",
  mfo: "Займы МФО",
  cpl: "CPL-заявки",
};

export function OfferCard({ offer, compact }: { offer: OfferCardType; compact?: boolean }) {
  const brandInitial = offer.brand.trim().charAt(0).toUpperCase() || "B";
  const actionClass = offer.available
    ? "bg-electric/10 text-electric group-hover:bg-electric/15"
    : "bg-white/[0.04] text-indigo-200/65";

  return (
    <Link
      to={`/offer/${offer.id}`}
      onClick={() => haptic("light")}
      aria-label={`${offer.brand}: ${offer.name}, награда ${offer.reward.toLocaleString("ru-RU")} рублей`}
      className="group card-glass block overflow-hidden transition-all duration-200 hover:-translate-y-0.5 hover:border-electric/35 active:scale-[0.985]"
    >
      <div className="relative aspect-video w-full overflow-hidden bg-[radial-gradient(circle_at_25%_20%,rgba(34,211,238,.18),transparent_42%),linear-gradient(135deg,#17234b,#090e20)]">
        <div className="absolute inset-0 flex items-center justify-center" aria-hidden="true">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.06] text-2xl font-black text-white/80 shadow-2xl">
            {brandInitial}
          </div>
        </div>
        {offer.image_url && (
          <img
            src={offer.image_url}
            alt={`${offer.brand} · ${offer.name}`}
            loading="lazy"
            decoding="async"
            width={900}
            height={520}
            onError={(event) => {
              event.currentTarget.style.display = "none";
            }}
            className="relative z-[1] h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.025]"
          />
        )}
        <div className="pointer-events-none absolute inset-0 z-[2] bg-gradient-to-t from-navy-950/90 via-transparent to-navy-950/10" />
        <span className="absolute left-3 top-3 z-[3] rounded-full border border-white/10 bg-navy-950/80 px-2.5 py-1 text-[11px] font-bold text-indigo-100 backdrop-blur">
          {CAT_LABEL[offer.category] ?? offer.category}
        </span>
        {offer.available ? (
          <span className="absolute right-3 top-3 z-[3] inline-flex items-center gap-1 rounded-full border border-emerald-glow/30 bg-navy-950/85 px-2.5 py-1 text-[10px] font-bold text-emerald-glow backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-glow" />
            Доступно
          </span>
        ) : (
          <span
            className="absolute right-3 top-3 z-[3] max-w-[60%] truncate rounded-full border border-gold/30 bg-navy-950/85 px-2.5 py-1 text-[10px] font-bold text-gold backdrop-blur"
            title={offer.unavailable_reason ?? undefined}
          >
            {offer.has_partner_link ? "Скоро" : "Нет ссылки"}
          </span>
        )}
      </div>

      <div className="space-y-3 p-3.5 sm:p-4">
        <div className="min-h-[42px]">
          <div className="truncate text-[10px] font-bold uppercase tracking-[0.14em] text-indigo-300/70">
            {offer.emoji} {offer.brand}
          </div>
          <div className="mt-1 line-clamp-2 text-[13px] font-extrabold leading-snug text-white sm:text-sm">
            {offer.name}
          </div>
        </div>

        <div className="flex items-end justify-between gap-2 border-t border-white/[0.07] pt-3">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-300/65">
              Вознаграждение
            </div>
            <div className="mt-0.5 whitespace-nowrap text-xl font-black tracking-tight text-gold-gradient">
              {offer.reward.toLocaleString("ru-RU")} ₽
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-200/75">
              <Icon name="clock" className="h-3.5 w-3.5 text-electric" />
              холд {offer.hold_days} дн.
            </div>
          </div>
        </div>

        {!compact && (
          <p className="line-clamp-2 text-[11px] leading-relaxed text-indigo-200/65">
            {offer.condition}
          </p>
        )}

        <div className={`flex items-center justify-between rounded-xl px-3 py-2.5 text-[11px] font-bold ${actionClass}`}>
          <span>{offer.available ? "Посмотреть условия" : "Узнать подробнее"}</span>
          <Icon name="chevron-right" className="h-4 w-4" />
        </div>
      </div>
    </Link>
  );
}
