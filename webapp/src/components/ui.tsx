import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "./Icon";
import type { AppStatus } from "../lib/types";

export function PageHeader({
  title,
  subtitle,
  back,
  right,
}: {
  title: string;
  subtitle?: string;
  back?: string;
  right?: ReactNode;
}) {
  return (
    <header className="flex items-center gap-3 px-5 pb-4 pt-5">
      {back !== undefined && (
        <Link
          to={back}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-royal/25 bg-navy-900/70 text-indigo-200"
          aria-label="Назад"
        >
          <Icon name="chevron-left" className="h-5 w-5" />
        </Link>
      )}
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-xl font-extrabold">{title}</h1>
        {subtitle && <p className="mt-0.5 truncate text-xs text-indigo-300/60">{subtitle}</p>}
      </div>
      {right}
    </header>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 mt-6 flex items-center justify-between px-5">
      <h2 className="text-sm font-bold uppercase tracking-wider text-indigo-300/70">{children}</h2>
      {action}
    </div>
  );
}

export function EmptyState({ icon, title, text }: { icon: IconName; title: string; text: string }) {
  return (
    <div className="card-glass mx-5 flex flex-col items-center gap-3 p-8 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-navy-800 text-indigo-300/70">
        <Icon name={icon} className="h-7 w-7" />
      </div>
      <div className="font-bold">{title}</div>
      <p className="text-sm leading-relaxed text-indigo-300/60">{text}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card-glass mx-5 flex flex-col items-center gap-3 p-6 text-center">
      <Icon name="cross" className="h-8 w-8 text-rose-alert" />
      <p className="text-sm text-indigo-200/80">{message}</p>
      {onRetry && (
        <button className="btn-ghost" onClick={onRetry}>
          <Icon name="refresh" className="h-4 w-4" /> Повторить
        </button>
      )}
    </div>
  );
}

export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3 px-5">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-24 w-full" />
      ))}
    </div>
  );
}

export function ProgressBar({ value, max, gold }: { value: number; max: number; gold?: boolean }) {
  const pct = Math.max(0, Math.min(100, (value / Math.max(1, max)) * 100));
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-navy-800">
      <div
        className={`h-full rounded-full transition-all duration-700 ${
          gold
            ? "bg-gradient-to-r from-amber-glow to-gold shadow-glow-gold"
            : "bg-gradient-to-r from-royal-soft to-electric"
        }`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

const STATUS_STYLE: Record<AppStatus, { label: string; cls: string }> = {
  new: { label: "Оформляешь", cls: "bg-electric/15 text-electric border-electric/30" },
  proof: { label: "На проверке", cls: "bg-royal/20 text-royal-soft border-royal/40" },
  hold: { label: "Холд", cls: "bg-amber-glow/15 text-gold border-gold/30" },
  confirmed: { label: "Подтверждено", cls: "bg-emerald-glow/15 text-emerald-glow border-emerald-glow/30" },
  paid: { label: "Выплачено", cls: "bg-emerald-deep/25 text-emerald-glow border-emerald-glow/40" },
  rejected: { label: "Отклонено", cls: "bg-rose-alert/15 text-rose-alert border-rose-alert/30" },
  expired: { label: "Истекло", cls: "bg-indigo-400/10 text-indigo-300/70 border-indigo-400/25" },
};

export function StatusBadge({ status }: { status: AppStatus }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.expired;
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-bold ${s.cls}`}>
      {s.label}
    </span>
  );
}

export function RewardTag({ amount, className = "" }: { amount: number; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 font-extrabold text-gold-gradient ${className}`}>
      <Icon name="coin" className="h-4 w-4 text-gold" />
      {amount.toLocaleString("ru-RU")} ₽
    </span>
  );
}