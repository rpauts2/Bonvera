import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setSession } from "../lib/api";

type WidgetUser = { id: number; first_name?: string; last_name?: string; username?: string; photo_url?: string; auth_date: number; hash: string };
declare global { interface Window { onBonveraTelegramAuth?: (user: WidgetUser) => void } }

export default function AdminLogin() {
  const [bot, setBot] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    // Opened as a Mini App: initData is already signed, no login widget needed.
    const tg = (window as unknown as { Telegram?: { WebApp?: { initData?: string } } }).Telegram?.WebApp;
    const initData = tg?.initData;
    if (!initData) return;
    api.post<{ token: string }>("/auth/telegram", { initData })
      .then((result) => { setSession(result.token); navigate("/admin", { replace: true }); })
      .catch(() => { /* fall back to the widget below */ });
  }, [navigate]);

  useEffect(() => {
    let active = true;
    api.get<{ bot_username: string }>("/admin/login-config").then((v) => {
      if (active) { setBot(v.bot_username); setLoading(false); }
    }).catch((e) => { if (active) { setError(e instanceof Error ? e.message : "Не удалось подключить вход Telegram"); setLoading(false); } });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!bot) return;
    window.onBonveraTelegramAuth = (user) => {
      setError("");
      void api.post<{ token: string }>("/auth/telegram-widget", user).then((result) => {
        setSession(result.token);
        navigate("/admin", { replace: true });
      }).catch((e) => setError(e instanceof Error ? e.message : "Не удалось войти"));
    };
    const script = document.createElement("script");
    script.id = "bonvera-telegram-login";
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", bot);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-radius", "12");
    script.setAttribute("data-userpic", "false");
    script.setAttribute("data-onauth", "onBonveraTelegramAuth(user)");
    document.getElementById("bonvera-login-slot")?.replaceChildren(script);
    return () => { window.onBonveraTelegramAuth = undefined; script.remove(); };
  }, [bot, navigate]);

  return <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-5 py-12 text-indigo-50">
    <div className="pointer-events-none absolute -left-28 top-1/4 h-80 w-80 rounded-full bg-cyan-500/10 blur-[100px]" />
    <div className="pointer-events-none absolute -right-24 bottom-0 h-96 w-96 rounded-full bg-violet-600/20 blur-[110px]" />
    <section className="relative w-full max-w-md rounded-[30px] border border-violet-400/20 bg-[#0a1022]/90 p-7 shadow-2xl shadow-violet-950/40 backdrop-blur-xl sm:p-9">
      <div className="mb-8 flex items-center gap-3"><div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-amber-300/30 bg-amber-300/10 text-2xl text-amber-300">♛</div><div><div className="text-[11px] font-black tracking-[.28em] text-cyan-300">BONVERA</div><div className="text-xs text-indigo-200/50">CONTROL CENTER</div></div></div>
      <div className="text-[10px] font-bold uppercase tracking-[.24em] text-violet-300">Защищённый доступ</div>
      <h1 className="mt-2 text-3xl font-extrabold tracking-tight">Панель управления</h1>
      <p className="mt-3 text-sm leading-6 text-indigo-200/65">Войди через Telegram. Доступ получат только аккаунты, добавленные в серверный список администраторов BONVERA.</p>
      <div className="mt-8 flex min-h-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[.03] p-3">
        {loading ? <span className="text-xs text-indigo-200/60">Подключаю Telegram…</span> : bot ? <div id="bonvera-login-slot" /> : <span className="text-xs text-rose-200">Виджет входа недоступен</span>}
      </div>
      {error && <p role="alert" className="mt-4 rounded-xl border border-rose-400/20 bg-rose-400/10 p-3 text-xs leading-5 text-rose-200">{error}</p>}
      <div className="mt-7 flex items-center gap-2 text-[10px] text-indigo-200/40"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400"/> Подпись Telegram проверяется сервером · Сессия ограничена по времени</div>
    </section>
  </main>;
}
