import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { Icon } from "../components/Icon";

type Overview = {
  users_total: number; users_active: number; offers_total: number; offers_enabled: number;
  apps_by_status: Record<string, number>; pending_payouts: number; pending_payouts_sum: number;
  recent_apps: Array<{id:number; user_id:number; offer:string; status:string; reward:number; created:string|null}>;
  recent_payouts: Array<{id:number; user_id:number; amount:number; status:string; created:string|null}>;
};
const money = (n:number) => `${new Intl.NumberFormat("ru-RU").format(n)} ₽`;
const date = (v:string|null) => v ? new Date(v).toLocaleString("ru-RU", {day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}) : "—";
const statusNames:Record<string,string> = {new:"Новые",proof:"Проверка",hold:"Холд",confirmed:"Подтверждены",paid:"Выплачены",rejected:"Отклонены",expired:"Истекли",pending:"Ожидает",processing:"В работе",review_required:"Сверка"};

export default function Admin() {
  const [data,setData] = useState<Overview|null>(null);
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState("");
  const load = useCallback(async () => { setLoading(true); setError(""); try { setData(await api.get<Overview>("/admin/overview")); } catch(e) { setError(e instanceof Error ? e.message : "Не удалось загрузить панель"); } finally { setLoading(false); } },[]);
  useEffect(()=>{ void load(); },[load]);
  if (loading && !data) return <main className="min-h-screen p-5 text-indigo-100"><div className="animate-pulse">Загружаю панель BONVERA…</div></main>;
  if (error && !data) return <main className="min-h-screen p-5 text-indigo-100"><div className="card-glass p-5"><Icon name="lock" className="mb-3 h-8 w-8 text-rose-300"/><h1 className="text-xl font-extrabold">Нет доступа</h1><p className="mt-2 text-sm text-indigo-200/70">{error}</p><p className="mt-3 text-xs text-indigo-300/50">Панель доступна только аккаунтам из списка администраторов.</p></div></main>;
  if (!data) return null;
  const stats = [
    ["Пользователи",data.users_total.toLocaleString("ru-RU"),`${data.users_active.toLocaleString("ru-RU")} активны`,"friends"],
    ["Офферы",`${data.offers_enabled} / ${data.offers_total}`,"активны / всего","catalog"],
    ["Заявки",Object.values(data.apps_by_status).reduce((a,b)=>a+b,0).toLocaleString("ru-RU"),"всего в системе","doc"],
    ["Выводы",String(data.pending_payouts),money(data.pending_payouts_sum),"wallet"],
  ] as const;
  return <main className="min-h-screen px-4 pb-10 pt-5 text-indigo-50 sm:px-6">
    <header className="mb-6 flex items-center justify-between gap-3"><div><div className="flex items-center gap-2 text-[10px] font-black tracking-[.24em] text-electric"><span className="h-2 w-2 rounded-full bg-emerald-400"/> BONVERA CONTROL</div><h1 className="mt-2 text-2xl font-black tracking-tight">Панель управления</h1><p className="mt-1 text-xs text-indigo-200/55">Операционная сводка проекта</p></div><button onClick={()=>void load()} className="rounded-xl border border-white/10 bg-white/5 p-3 text-indigo-200"><Icon name="refresh"/></button></header>
    <section className="grid grid-cols-2 gap-3">{stats.map(([label,value,note,icon])=><article key={label} className="card-glass min-w-0 p-4"><div className="flex items-center justify-between text-xs text-indigo-200/60"><span>{label}</span><Icon name={icon} className="h-4 w-4 text-electric"/></div><div className="mt-3 text-2xl font-black tracking-tight">{value}</div><div className="mt-1 truncate text-[11px] text-indigo-200/50">{note}</div></article>)}</section>
    <section className="mt-6"><div className="mb-3 flex items-center justify-between"><h2 className="text-base font-extrabold">Статусы заявок</h2><span className="text-[10px] text-indigo-300/50">Все сделки</span></div><div className="card-glass grid grid-cols-2 gap-3 p-4">{Object.entries(data.apps_by_status).map(([key,count])=><div key={key} className="flex items-center justify-between gap-2"><span className="text-xs text-indigo-200/70">{statusNames[key]??key}</span><b className="text-sm tabular-nums">{count}</b></div>)}</div></section>
    <section className="mt-6"><h2 className="mb-3 text-base font-extrabold">Последние заявки</h2><div className="space-y-2">{data.recent_apps.length ? data.recent_apps.map(a=><article key={a.id} className="card-glass flex items-center justify-between gap-3 p-3"><div className="min-w-0"><div className="truncate text-sm font-bold">{a.offer}</div><div className="mt-1 text-[10px] text-indigo-200/50">#{a.id} · UID {a.user_id} · {date(a.created)}</div></div><div className="shrink-0 text-right"><div className="text-xs font-bold">{money(a.reward)}</div><div className="mt-1 text-[10px] text-electric">{statusNames[a.status]??a.status}</div></div></article>) : <p className="card-glass p-4 text-xs text-indigo-200/50">Заявок пока нет</p>}</div></section>
    <section className="mt-6"><h2 className="mb-3 text-base font-extrabold">Последние запросы на вывод</h2><div className="space-y-2">{data.recent_payouts.length ? data.recent_payouts.map(p=><article key={p.id} className="card-glass flex items-center justify-between gap-3 p-3"><div><div className="text-sm font-bold">Вывод #{p.id}</div><div className="mt-1 text-[10px] text-indigo-200/50">UID {p.user_id} · {date(p.created)}</div></div><div className="text-right"><div className="text-sm font-bold">{money(p.amount)}</div><div className="mt-1 text-[10px] text-electric">{statusNames[p.status]??p.status}</div></div></article>) : <p className="card-glass p-4 text-xs text-indigo-200/50">Запросов пока нет</p>}</div></section>
    <p className="mt-8 text-center text-[10px] text-indigo-300/35">Доступ ограничен серверной проверкой Telegram ID администратора.</p>
  </main>;
}
