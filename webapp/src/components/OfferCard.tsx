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
  return (
    <Link
      to={`/offer/${offer.id}`}
      onClick={() => haptic("light")}
      className="card-glass block overflow-hidden transition-transform active:scale-[0.98]"
    >
      <div className="relative h-32 w-full overflow-hidden bg-navy-800">
        <img
          src={offer.image_url}
          alt={`${offer.brand} · ${offer.name}`}
          loading="lazy"
          decoding="async"
          width={900}
          height={520}
          className="h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-navy-950/90 via-transparent to-transparent" />
        <span className="absolute left-3 top-3 rounded-full border border-royal/30 bg-navy-950/80 px-2.5 py-1 text-[12px] font-bold text-indigo-200 backdrop-blur">
          {CAT_LABEL[offer.category] ?? offer.category}
        </span>
        {!offer.available && (
          <span
            className="absolute right-3 top-3 max-w-[60%] truncate rounded-full border border-gold/30 bg-navy-950/85 px-2.5 py-1 text-[12px] font-bold text-gold backdrop-blur"
            title={offer.unavailable_reason ?? undefined}
          >
            {offer.has_partner_link ? "Скоро" : "Нет ссылки"}
          </span>
        )}
      </div>
      <div className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-[12px] font-semibold uppercase tracking-wide text-indigo-300/75">
              {offer.emoji} {offer.brand}
            </div>
            <div className="line-clamp-2 text-sm font-bold leading-snug">{offer.name}</div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-base font-extrabold text-gold-gradient">
              {offer.reward.toLocaleString("ru-RU")} ₽
            </div>
            <div className="text-[12px] text-indigo-300/70">награда</div>
          </div>
        </div>
        {!compact && (
          <p className="line-clamp-2 text-xs leading-relaxed text-indigo-200/60">{offer.condition}</p>
        )}
        <div className="flex items-center justify-between pt-1 text-[12px] text-indigo-300/75">
          <span className="inline-flex items-center gap-1">
            <Icon name="clock" className="h-3.5 w-3.5" /> холд {offer.hold_days} дн.
          </span>
          <span className="inline-flex items-center gap-1 font-bold text-electric">
            Подробнее <Icon name="chevron-right" className="h-3.5 w-3.5" />
          </span>
        </div>
      </div>
    </Link>
  );
}