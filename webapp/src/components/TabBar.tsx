import { useEffect, useRef } from "react";
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
  const barRef = useRef<HTMLDivElement | null>(null);

  // Публикуем реальную высоту панели, чтобы контент под ней не перекрывался
  // ни на одной высоте экрана и ни при любом размере шрифта.
  useEffect(() => {
    const el = barRef.current;
    if (!el) return;
    const publish = () => {
      const h = Math.round(el.getBoundingClientRect().height);
      if (h > 0) document.documentElement.style.setProperty("--tabbar-h", `${h}px`);
    };
    publish();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", publish);
      return () => window.removeEventListener("resize", publish);
    }
    const ro = new ResizeObserver(publish);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <nav
      className="app-shell pointer-events-none fixed inset-x-0 bottom-0 z-40"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      <div
        ref={barRef}
        className="pointer-events-auto mx-3 mb-2 flex items-stretch justify-between rounded-3xl border border-royal/25 bg-navy-950/90 px-2 py-2 shadow-card backdrop-blur-xl"
      >
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.to === "/"}
            onClick={() => haptic("light")}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-1 rounded-2xl px-1 py-2 text-[12px] font-semibold transition-colors ${
                isActive ? "text-electric" : "text-indigo-300/70"
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
