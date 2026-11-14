import { NavLink } from "react-router-dom";
import { haptic } from "../lib/telegram";
import { Icon } from "./Icon";

const tabs = [
  { to: "/", label: "Главная", icon: "home" as const },
  { to: "/tasks", label: "Задания", icon: "tasks" as const },
  { to: "/catalog", label: "Каталог", icon: "catalog" as const },
  { to: "/friends", label: "Друзья", icon: "friends" as const },
  { to: "/profile", label: "Профиль", icon: "profile" as const },
];

export function TabBar() {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 mx-auto w-full max-w-[520px]"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      <div className="mx-3 mb-2 flex items-stretch justify-between rounded-3xl border border-royal/25 bg-navy-950/90 px-2 py-2 shadow-card backdrop-blur-xl">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.to === "/"}
            onClick={() => haptic("light")}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-1 rounded-2xl px-1 py-2 text-[10px] font-semibold transition-colors ${
                isActive ? "text-electric" : "text-indigo-300/60"
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-xl transition-all ${
                    isActive
                      ? "bg-electric/15 shadow-glow-electric"
                      : "bg-transparent"
                  }`}
                >
                  <Icon name={t.icon} className="h-5 w-5" />
                </span>
                {t.label}
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}