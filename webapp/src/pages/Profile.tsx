import { Link } from "react-router-dom";
import { useSession } from "../state/session";
import { fmtDate, rub } from "../lib/api";
import { Icon, type IconName } from "../components/Icon";
import { PageHeader } from "../components/ui";
import { haptic } from "../lib/telegram";

const MENU: Array<{ to: string; icon: IconName; label: string; hint: string }> = [
  { to: "/wallet", icon: "wallet", label: "Кошелёк", hint: "Баланс и операции" },
  { to: "/apps", icon: "doc", label: "Мои заявки", hint: "Статусы и подтверждения" },
  { to: "/history", icon: "clock", label: "История операций", hint: "Все начисления и списания" },
  { to: "/achievements", icon: "trophy", label: "Достижения", hint: "Бонусные вехи" },
  { to: "/leaderboard", icon: "crown", label: "Рейтинг", hint: "Заказы и друзья" },
  { to: "/settings", icon: "shield", label: "Настройки СБП", hint: "Банк и телефон для выплат" },
  { to: "/support", icon: "support", label: "Поддержка", hint: "Вопросы и помощь" },
  { to: "/rules", icon: "doc", label: "Правила сервиса", hint: "Условия и риски" },
];

export default function Profile() {
  const { user, logout } = useSession();
  if (!user) return null;

  const initial = (user.name ?? user.username ?? "B").trim().charAt(0).toUpperCase();

  return (
    <div>
      <PageHeader title="Профиль" back="/" />
      <section className="px-5">
        <div className="card-glass flex items-center gap-4 p-5">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border border-gold/40 bg-navy-800 text-2xl font-extrabold text-gold-gradient shadow-glow-gold">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-lg font-extrabold">{user.name ?? "Игрок"}</div>
            {user.username && <div className="truncate text-xs text-electric">@{user.username}</div>}
            <div className="mt-1 flex items-center gap-2 text-[12px] text-indigo-300/75">
              <span className="rounded-full border border-royal/30 bg-royal/15 px-2 py-0.5 font-bold text-royal-soft">
                Уровень {user.level}
              </span>
              <span>с {fmtDate(user.created)}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="mt-3 grid grid-cols-2 gap-3 px-5">
        <div className="card-glass p-4 text-center">
          <div className="text-xl font-extrabold text-gold-gradient">{rub(user.balance)}</div>
          <div className="mt-1 text-[12px] text-indigo-300/75">баланс кошелька</div>
        </div>
        <div className="card-glass p-4 text-center">
          <div className="text-xl font-extrabold text-emerald-glow">{user.confirmed_orders}</div>
          <div className="mt-1 text-[12px] text-indigo-300/75">подтверждённых заказов</div>
        </div>
      </section>

      <section className="mt-4 space-y-2 px-5">
        {MENU.map((m) => (
          <Link
            key={m.to}
            to={m.to}
            onClick={() => haptic("light")}
            className="card-glass flex items-center gap-3 p-4 transition-transform active:scale-[0.99]"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-royal/15 text-royal-soft">
              <Icon name={m.icon} className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-bold">{m.label}</div>
              <div className="truncate text-[12px] text-indigo-300/70">{m.hint}</div>
            </div>
            <Icon name="chevron-right" className="h-4 w-4 shrink-0 text-indigo-300/40" />
          </Link>
        ))}
      </section>

      <section className="px-5 pb-6 pt-4">
        <button
          className="btn-ghost w-full text-rose-alert"
          onClick={() => {
            haptic("medium");
            logout();
          }}
        >
          <Icon name="logout" className="h-4 w-4" /> Выйти из сессии
        </button>
        <p className="mt-3 text-center text-[12px] text-indigo-300/40">
          ID {user.id} · BONVERA не запрашивает пароли, CVV и коды из SMS
        </p>
      </section>
    </div>
  );
}