import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../lib/api";

type Slot = { slot_number:number; kind:"mfo_offer"|"storefront"; advertiser_name:string; title:string; description:string; target_url:string; tracking_param:string; enabled:boolean };
type Campaign = { id:number; name:string; status:string; advertiser_name:string; recipient_count:number; sent_count:number; skipped_count:number; failed_count:number; erid:string; created:string|null };
type Overview = { vk_enabled:boolean; contacts_total:number; marketing_opt_in:number; suppressed:number; campaigns_total:number; clicks_total:number; configured_slots:number; slots_total:number; community_url:string; campaigns:Campaign[] };
type Preview = { total:number; valid_count:number; duplicate_count:number; rows:Array<Record<string,unknown>>; errors:Array<{line:number;reason:string}> };
type CampaignPreview = { campaign_id:number; total_contacts:number; eligible_by_consent:number; excluded_by_consent:number };

const initialSlots = ():Slot[] => Array.from({length:5},(_,i)=>({slot_number:i+1,kind:i===4?"storefront":"mfo_offer",advertiser_name:"",title:i===4?"Все предложения Bonvera":"МФО №"+(i+1),description:"",target_url:"",tracking_param:"",enabled:false}));
const panel = "rounded-2xl border border-white/[.07] bg-[#10182b]/80 shadow-xl shadow-black/10";
const field = "mt-1 w-full rounded-xl border border-white/10 bg-[#080f20] px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-300/40";
const label = "block text-[11px] font-semibold text-indigo-100/65";
const statusLabel:Record<string,string> = {draft:"Черновик",running:"Выполняется",paused:"Приостановлена",completed:"Завершена",cancelled:"Отменена",failed:"Ошибка"};
const statusStyle:Record<string,string> = {draft:"text-slate-300 bg-slate-400/10",running:"text-cyan-200 bg-cyan-300/10",paused:"text-amber-200 bg-amber-300/10",completed:"text-emerald-200 bg-emerald-300/10",failed:"text-rose-200 bg-rose-300/10"};

export default function AdminVk() {
  const navigate = useNavigate();
  const [tab,setTab] = useState("overview");
  const [overview,setOverview] = useState<Overview|null>(null);
  const [slots,setSlots] = useState<Slot[]>(initialSlots());
  const [campaigns,setCampaigns] = useState<Campaign[]>([]);
  const [loading,setLoading] = useState(true);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const [name,setName] = useState("VK · предложения МФО");
  const [textValue,setTextValue] = useState("Нужен микрозайм? Посмотрите предложения четырёх микрофинансовых организаций. Некоторые кредиторы рассматривают заявки заёмщиков с разной кредитной историей. Ознакомьтесь с условиями и подайте заявку напрямую выбранной компании.");
  const [advertiser,setAdvertiser] = useState("");
  const [inn,setInn] = useState("");
  const [erid,setErid] = useState("");
  const [cta,setCta] = useState("Посмотреть предложения");
  const [draftId,setDraftId] = useState<number|null>(null);
  const [campaignPreview,setCampaignPreview] = useState<CampaignPreview|null>(null);
  const [csv,setCsv] = useState("");
  const [csvPreview,setCsvPreview] = useState<Preview|null>(null);
  const [contacts,setContacts] = useState<Array<Record<string,unknown>>>([]);
  const [contactQuery,setContactQuery] = useState("");

  const handleError = useCallback((e:unknown) => {
    if (e instanceof ApiError && e.status === 401) { navigate("/admin/login",{replace:true}); return; }
    setError(e instanceof Error ? e.message : "Не удалось выполнить запрос.");
  },[navigate]);

  const loadOverview = useCallback(async()=>setOverview(await api.get<Overview>("/admin/vk/overview")),[]);
  const loadSlots = useCallback(async()=>{const d=await api.get<{slots:Slot[]}>("/admin/vk/slots");setSlots(d.slots);},[]);
  const loadCampaigns = useCallback(async()=>{const d=await api.get<{items:Campaign[]}>("/admin/vk/campaigns");setCampaigns(d.items);},[]);
  const loadContacts = useCallback(async()=>{const p=new URLSearchParams();if(contactQuery.trim())p.set("q",contactQuery.trim());const d=await api.get<{items:Array<Record<string,unknown>>;total:number}>("/admin/vk/contacts?"+p.toString());setContacts(d.items);},[contactQuery]);

  const reloadAll = useCallback(async()=>{
    setLoading(true);setError("");
    try { await Promise.all([loadOverview(),loadSlots(),loadCampaigns()]); }
    catch(e){handleError(e);} finally{setLoading(false);}
  },[handleError,loadCampaigns,loadOverview,loadSlots]);

  useEffect(()=>{void reloadAll();},[reloadAll]);
  useEffect(()=>{if(tab==="contacts")void loadContacts().catch(handleError);},[tab,loadContacts,handleError]);

  const setSlot = (index:number,patch:Partial<Slot>) => setSlots(old=>old.map((x,i)=>i===index?{...x,...patch}:x));
  const saveSlots = async()=>{
    setBusy(true);setError("");setNotice("");
    try {const result=await api.put<{saved:number}>("/admin/vk/slots",{slots});setNotice("Сохранено ссылок: "+result.saved+". Пятая ссылка остаётся пустой, пока ты не добавишь CPA-витрину.");await Promise.all([loadSlots(),loadOverview()]);}
    catch(e){handleError(e);}finally{setBusy(false);}
  };
  const createDraft = async()=>{
    setBusy(true);setError("");setNotice("");setCampaignPreview(null);
    try {const result=await api.post<{id:number}>("/admin/vk/campaigns",{name,text:textValue,cta_label:cta,advertiser_name:advertiser,advertiser_inn:inn,erid,warning_text:"Оценивайте свои финансовые возможности и риски."});setDraftId(result.id);setNotice("Черновик кампании #"+result.id+" сохранён. Для отправки потребуются рекламодатель, ИНН, ERID и все пять ссылок.");await loadCampaigns();}
    catch(e){handleError(e);}finally{setBusy(false);}
  };
  const previewDraft = async()=>{
    if(!draftId)return;setBusy(true);setError("");
    try{setCampaignPreview(await api.post<CampaignPreview>("/admin/vk/campaigns/"+draftId+"/preview",{}));}
    catch(e){handleError(e);}finally{setBusy(false);}
  };
  const sendDraft = async()=>{
    if(!draftId||!campaignPreview)return;
    if(!window.confirm("Запустить рекламную кампанию? Перед каждым сообщением будут повторно проверены согласие и разрешение VK."))return;
    setBusy(true);setError("");
    try{const r=await api.post<{queued:number}>("/admin/vk/campaigns/"+draftId+"/send",{confirm:true});setNotice("Кампания запущена. В очереди: "+r.queued);setCampaignPreview(null);await Promise.all([loadCampaigns(),loadOverview()]);}
    catch(e){handleError(e);}finally{setBusy(false);}
  };
  const campaignAction = async(c:Campaign,action:"pause"|"resume")=>{
    if(action==="resume"&&!window.confirm("Возобновить рассылку оставшимся подходящим получателям?"))return;
    setBusy(true);setError("");
    try{await api.post("/admin/vk/campaigns/"+c.id+"/"+action,{confirm:true});setNotice(action==="pause"?"Кампания приостановлена.":"Кампания возобновлена.");await loadCampaigns();}
    catch(e){handleError(e);}finally{setBusy(false);}
  };
  const previewCsv = async()=>{
    setBusy(true);setError("");setCsvPreview(null);
    try{const r=await api.post<Preview>("/admin/vk/contacts/import/preview",{csv_text:csv});setCsvPreview(r);setNotice("Проверка CSV: пригодно "+r.valid_count+", дубликатов "+r.duplicate_count+", ошибок "+r.errors.length+".");}
    catch(e){handleError(e);}finally{setBusy(false);}
  };
  const commitCsv = async()=>{
    if(!csvPreview||csvPreview.errors.length||!csvPreview.valid_count)return;
    if(!window.confirm("Импортировать "+csvPreview.valid_count+" VK-контактов с подтверждёнными согласиями?"))return;
    setBusy(true);setError("");
    try{const r=await api.post<{created:number;updated:number;suppressed:number}>("/admin/vk/contacts/import/commit",{csv_text:csv});setNotice("Импорт завершён. Новых: "+r.created+", обновлено: "+r.updated+", исключено из-за отписки: "+r.suppressed+".");setCsv("");setCsvPreview(null);await Promise.all([loadContacts(),loadOverview()]);}
    catch(e){handleError(e);}finally{setBusy(false);}
  };

  const tabs=[["overview","Обзор"],["links","Пять ссылок"],["campaigns","Кампании"],["contacts","Контакты и импорт"],["acquisition","Привлечение"]];
  const configuredSlots=slots.filter(s=>s.enabled&&s.target_url.trim()).length;
  if(loading)return <main className="min-h-screen bg-[#070d1b] p-8 text-indigo-100">Загружаю VK Marketing…</main>;

  return <main className="mx-auto min-h-screen w-full max-w-[1500px] bg-[#070d1b] px-4 pb-12 pt-6 text-indigo-50 sm:px-6 lg:px-8">
    <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3"><div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-cyan-300/20 bg-cyan-300/10 text-xl font-black text-cyan-200">VK</div><div><div className="text-[10px] font-black tracking-[.28em] text-cyan-300">BONVERA GROWTH</div><h1 className="mt-1 text-2xl font-black">VK Marketing</h1><p className="text-xs text-indigo-200/45">VK-бот · МФО-воронка · кампании · tracking</p></div></div>
      <div className="flex gap-2"><button onClick={()=>navigate("/admin")} className="rounded-xl border border-white/10 px-4 py-2.5 text-xs font-bold text-indigo-100 hover:bg-white/5">Назад в админку</button><button onClick={()=>void reloadAll()} className="rounded-xl bg-cyan-300/10 px-4 py-2.5 text-xs font-bold text-cyan-200 hover:bg-cyan-300/15">Обновить</button></div>
    </header>

    {error&&<div role="alert" className="mb-4 rounded-xl border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200">{error}</div>}
    {notice&&<div className="mb-4 rounded-xl border border-emerald-400/20 bg-emerald-400/10 p-3 text-sm text-emerald-200">{notice}</div>}

    <nav className={panel+" mb-5 flex flex-wrap gap-2 p-2"}>
      {tabs.map(([id,title])=><button key={id} onClick={()=>setTab(id)} className={"rounded-xl px-4 py-2.5 text-xs font-bold transition "+(tab===id?"bg-cyan-300/15 text-cyan-100 ring-1 ring-cyan-300/20":"text-indigo-200/60 hover:bg-white/5")}>{title}</button>)}
    </nav>

    {tab==="overview"&&overview&&<section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[["Контакты VK",overview.contacts_total],["Согласились на рекламу",overview.marketing_opt_in],["Отписались / исключены",overview.suppressed],["Переходы по ссылкам",overview.clicks_total]].map(([title,value])=><article className={panel+" p-5"} key={String(title)}><div className="text-xs text-indigo-200/50">{title}</div><div className="mt-3 text-3xl font-black tabular-nums">{Number(value).toLocaleString("ru-RU")}</div></article>)}
      <article className={panel+" p-5 sm:col-span-2 xl:col-span-4"}>
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-extrabold">Состояние канала</h2><p className="mt-1 text-xs text-indigo-200/55">Настроено ссылок: {overview.configured_slots}/5 · кампаний: {overview.campaigns_total}</p></div><span className={"rounded-full px-3 py-1.5 text-xs font-bold "+(overview.vk_enabled?"bg-emerald-400/10 text-emerald-200":"bg-amber-300/10 text-amber-200")}>{overview.vk_enabled?"VK включён":"VK выключен"}</span></div>
        {!overview.vk_enabled&&<p className="mt-4 rounded-xl border border-amber-300/15 bg-amber-300/[.05] p-3 text-xs leading-5 text-amber-100/75">VK-бот пока не активен. Нужно настроить сообщество VK, Callback API, group token и публичный HTTPS в серверных переменных. Telegram продолжает работать независимо.</p>}
      </article>
      <article className={panel+" p-5 sm:col-span-2 xl:col-span-4"}><h2 className="mb-3 text-lg font-extrabold">Последние кампании</h2>{campaigns.length===0?<p className="text-sm text-indigo-200/45">Кампаний пока нет.</p>:<div className="space-y-2">{campaigns.map(c=><div key={c.id} className="flex flex-wrap items-center gap-3 rounded-xl bg-white/[.03] p-3"><div className="min-w-[180px] flex-1"><div className="text-sm font-bold">{c.name}</div><div className="mt-1 text-[11px] text-indigo-200/45">#{c.id} · {c.advertiser_name}</div></div><span className={"rounded-full px-2.5 py-1 text-[10px] font-bold "+(statusStyle[c.status]||"bg-white/5 text-slate-300")}>{statusLabel[c.status]||c.status}</span><div className="text-right text-xs tabular-nums text-indigo-100/70">{c.sent_count}/{c.recipient_count} отправлено</div></div>)}</div>}</article>
    </section>}

    {tab==="links"&&<section className={panel+" p-5"}>
      <div className="mb-5"><h2 className="text-lg font-extrabold">Пять кнопок в VK-боте</h2><p className="mt-1 text-xs leading-5 text-indigo-200/55">Первые четыре — прямые предложения МФО. Пятая — твоя внешняя CPA-витрина; URL не заполняю и не генерирую.</p></div>
      <div className="grid gap-4 xl:grid-cols-2">{slots.map((slot,index)=><article className="rounded-2xl border border-white/[.07] bg-[#0a1224] p-4" key={slot.slot_number}>
        <div className="mb-3 flex items-center justify-between gap-3"><div><div className="text-[10px] font-black tracking-[.2em] text-cyan-300">СЛОТ {slot.slot_number}</div><h3 className="mt-1 font-extrabold">{slot.slot_number===5?"CPA-витрина":"МФО №"+slot.slot_number}</h3></div><label className="flex items-center gap-2 text-xs text-indigo-100/65"><input type="checkbox" checked={slot.enabled} onChange={e=>setSlot(index,{enabled:e.target.checked})}/>Включён</label></div>
        <div className="grid gap-3 sm:grid-cols-2"><label className={label}>Рекламодатель<input className={field} value={slot.advertiser_name} onChange={e=>setSlot(index,{advertiser_name:e.target.value})} placeholder="Название МФО"/></label><label className={label}>Название кнопки<input className={field} value={slot.title} onChange={e=>setSlot(index,{title:e.target.value})} placeholder="Название кнопки"/></label></div>
        <label className={label+" mt-3"}>Партнёрская ссылка / CPA URL<input className={field} value={slot.target_url} onChange={e=>setSlot(index,{target_url:e.target.value})} placeholder={slot.slot_number===5?"Вставишь свою ссылку на CPA-витрину":"https://..."}/></label>
        <div className="mt-3 grid gap-3 sm:grid-cols-2"><label className={label}>Tracking-параметр<input className={field} value={slot.tracking_param} onChange={e=>setSlot(index,{tracking_param:e.target.value})} placeholder="subid / sub1 / click_id"/></label><label className={label}>Описание<input className={field} value={slot.description} onChange={e=>setSlot(index,{description:e.target.value})} placeholder="Короткое описание"/></label></div>
        <p className="mt-3 break-all text-[10px] text-indigo-200/35">{slot.target_url?slot.target_url:"Ссылка не задана"}</p>
      </article>)}</div>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-indigo-200/45">Активно настроено: {configuredSlots}/5. Принимаются только HTTPS-ссылки. Телефон и VK ID в URL не передаются.</p><button disabled={busy} onClick={()=>void saveSlots()} className="rounded-xl bg-cyan-300/15 px-5 py-3 text-xs font-extrabold text-cyan-100 disabled:opacity-40">{busy?"Сохраняю…":"Сохранить пять ссылок"}</button></div>
    </section>}

    {tab==="campaigns"&&<section className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(340px,.9fr)]">
      <article className={panel+" p-5"}>
        <h2 className="text-lg font-extrabold">Создать рекламную кампанию</h2><p className="mb-4 mt-1 text-xs leading-5 text-indigo-200/55">Черновик можно сохранить заранее. Отправка требует рекламодателя, ИНН, ERID и все пять ссылок.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className={label}>Название кампании<input className={field} value={name} onChange={e=>setName(e.target.value)}/></label>
          <label className={label}>Текст кнопки<input className={field} value={cta} onChange={e=>setCta(e.target.value)}/></label>
          <label className={label+" sm:col-span-2"}>Рекламодатель<input className={field} value={advertiser} onChange={e=>setAdvertiser(e.target.value)} placeholder="Юридическое наименование рекламодателя"/></label>
          <label className={label}>ИНН рекламодателя<input className={field} value={inn} onChange={e=>setInn(e.target.value)} placeholder="10 или 12 цифр"/></label>
          <label className={label}>ERID<input className={field} value={erid} onChange={e=>setErid(e.target.value)} placeholder="Токен маркировки рекламы"/></label>
        </div>
        <label className={label+" mt-3"}>Текст сообщения<textarea className={field+" min-h-[180px] resize-y"} maxLength={3500} value={textValue} onChange={e=>setTextValue(e.target.value)}/></label>
        <div className="mt-3 rounded-xl border border-amber-300/10 bg-amber-300/[.04] p-3 text-xs leading-5 text-amber-100/65">Предупреждение «Оценивайте свои финансовые возможности и риски» добавляется автоматически. Нельзя заявлять о персональном одобрении без подтверждения конкретной МФО.</div>
        <div className="mt-4 flex flex-wrap gap-2"><button disabled={busy} onClick={()=>void createDraft()} className="rounded-xl bg-cyan-300/15 px-4 py-3 text-xs font-extrabold text-cyan-100 disabled:opacity-40">{busy?"Сохраняю…":"Сохранить черновик"}</button>{draftId!==null&&<button disabled={busy} onClick={()=>void previewDraft()} className="rounded-xl border border-white/10 px-4 py-3 text-xs font-bold text-indigo-100">Проверить аудиторию</button>}{draftId!==null&&<button disabled={busy||!campaignPreview||campaignPreview.eligible_by_consent===0} onClick={()=>void sendDraft()} className="rounded-xl bg-emerald-400/15 px-4 py-3 text-xs font-extrabold text-emerald-100 disabled:opacity-40">Запустить рассылку</button>}</div>
        {campaignPreview&&<div className="mt-4 grid grid-cols-3 gap-2">{[["Всего",campaignPreview.total_contacts],["Согласие есть",campaignPreview.eligible_by_consent],["Исключено",campaignPreview.excluded_by_consent]].map(([title,value])=><div className="rounded-xl bg-white/[.04] p-3" key={String(title)}><div className="text-[10px] text-indigo-200/45">{title}</div><div className="mt-1 text-xl font-black tabular-nums">{Number(value)}</div></div>)}<p className="col-span-3 text-[10px] text-indigo-200/40">VK permission каждого человека будет проверено непосредственно перед отправкой.</p></div>}
      </article>
      <article className={panel+" p-5"}><h2 className="mb-4 text-lg font-extrabold">История кампаний</h2>{campaigns.length===0?<p className="text-sm text-indigo-200/45">Кампаний пока нет.</p>:<div className="space-y-3">{campaigns.map(c=><div className="rounded-xl border border-white/[.06] bg-white/[.025] p-3" key={c.id}><div className="flex flex-wrap items-start justify-between gap-2"><div><div className="text-sm font-bold">{c.name}</div><div className="mt-1 text-[10px] text-indigo-200/40">#{c.id} · {c.advertiser_name}</div></div><span className={"rounded-full px-2 py-1 text-[10px] font-bold "+(statusStyle[c.status]||"bg-white/5 text-slate-300")}>{statusLabel[c.status]||c.status}</span></div><div className="mt-3 grid grid-cols-3 gap-2 text-center">{[["Отправлено",c.sent_count],["Пропущено",c.skipped_count],["Ошибки",c.failed_count]].map(([title,value])=><div className="rounded-lg bg-black/20 p-2" key={String(title)}><div className="text-lg font-black">{Number(value)}</div><div className="text-[9px] text-indigo-200/40">{title}</div></div>)}</div>{(c.status==="running"||c.status==="paused")&&<button disabled={busy} onClick={()=>void campaignAction(c,c.status==="running"?"pause":"resume")} className="mt-3 rounded-lg border border-white/10 px-3 py-2 text-[10px] font-bold text-indigo-100 disabled:opacity-40">{c.status==="running"?"Приостановить":"Возобновить"}</button>}</div>)}</div>}</article>
    </section>}

    {tab==="contacts"&&<section className="grid gap-5 xl:grid-cols-2">
      <article className={panel+" p-5"}><h2 className="text-lg font-extrabold">Импорт списка VK-пользователей</h2><p className="mt-1 text-xs leading-5 text-indigo-200/55">Нужны VK ID и отдельные доказательства согласия на обработку персональных данных и рекламные сообщения. Телефонный список сам по себе не позволяет отправлять сообщения VK.</p>
        <textarea className={field+" mt-4 min-h-[240px] resize-y font-mono text-[11px] leading-5"} value={csv} onChange={e=>{setCsv(e.target.value);setCsvPreview(null);}} placeholder={"vk_user_id,personal_data_consent_at,personal_data_consent_source,personal_data_consent_version,personal_data_consent_proof,marketing_consent_at,marketing_consent_source,marketing_consent_version,marketing_consent_proof
123456,2026-11-20T10:00:00Z,privacy-form,privacy-v1,proof-1,2026-11-20T10:00:00Z,marketing-form,marketing-v1,proof-2"}/>
        <div className="mt-3 flex flex-wrap gap-2"><button disabled={busy||!csv.trim()} onClick={()=>void previewCsv()} className="rounded-xl border border-cyan-300/20 bg-cyan-300/10 px-4 py-2.5 text-xs font-bold text-cyan-100 disabled:opacity-40">Проверить список</button><button disabled={busy||!csvPreview||csvPreview.errors.length>0||csvPreview.valid_count===0} onClick={()=>void commitCsv()} className="rounded-xl bg-emerald-400/15 px-4 py-2.5 text-xs font-extrabold text-emerald-100 disabled:opacity-40">Импортировать</button></div>
        {csvPreview&&<div className="mt-4 rounded-xl bg-white/[.04] p-3 text-xs"><div className="flex flex-wrap gap-3"><span>Всего: <b>{csvPreview.total}</b></span><span>Готово: <b>{csvPreview.valid_count}</b></span><span>Дубликаты: <b>{csvPreview.duplicate_count}</b></span><span>Ошибки: <b>{csvPreview.errors.length}</b></span></div>{csvPreview.errors.length>0&&<div className="mt-3 max-h-36 space-y-1 overflow-auto text-rose-200">{csvPreview.errors.slice(0,20).map(e=><p key={e.line}>Строка {e.line}: {e.reason}</p>)}</div>}</div>}
      </article>
      <article className={panel+" p-5"}><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-extrabold">Контакты VK</h2><p className="text-xs text-indigo-200/45">Сведения о телефонах показываются только в маскированном виде.</p></div><button onClick={()=>void loadContacts().catch(handleError)} className="rounded-lg border border-white/10 px-3 py-2 text-xs">Обновить</button></div>
        <form className="mt-3 flex gap-2" onSubmit={e=>{e.preventDefault();void loadContacts().catch(handleError);}}><input className={field+" mt-0"} value={contactQuery} onChange={e=>setContactQuery(e.target.value)} placeholder="Поиск по VK ID"/><button className="rounded-xl bg-white/5 px-3 text-xs font-bold">Найти</button></form>
        <div className="mt-4 max-h-[470px] space-y-2 overflow-auto">{contacts.map(x=><div key={String(x.vk_user_id)} className="rounded-xl bg-white/[.03] p-3"><div className="flex items-center justify-between gap-2"><b className="text-xs">VK ID {String(x.vk_user_id)}</b><span className={"text-[10px] font-bold "+(x.marketing_consent_at&&!x.marketing_suppressed?"text-emerald-200":"text-amber-200")}>{x.marketing_consent_at&&!x.marketing_suppressed?"Реклама разрешена":"Не включён в рекламу"}</span></div><div className="mt-1 text-[11px] text-indigo-200/50">{String(x.first_name||"")} {String(x.last_name||"")} · {String(x.phone||"Телефон не указан")}</div></div>)}{contacts.length===0&&<p className="py-10 text-center text-xs text-indigo-200/40">Контактов пока нет.</p>}</div>
      </article>
    </section>}

    {tab==="acquisition"&&<section className="grid gap-5 xl:grid-cols-2">
      <article className={panel+" p-5"}><h2 className="text-lg font-extrabold">Поиск и привлечение новой аудитории</h2><p className="mt-2 text-sm leading-6 text-indigo-200/60">Новые пользователи приходят через официальные рекламные объявления VK, которые ведут в диалог сообщества. Бот не сканирует чужие профили, не собирает ID участников групп и не пишет незнакомым людям первым.</p><div className="mt-4 rounded-xl border border-cyan-300/10 bg-cyan-300/[.04] p-4"><div className="text-xs font-bold text-cyan-100">Рекламный кабинет VK</div><a className="mt-2 inline-block text-sm font-bold text-cyan-200 underline" href="https://ads.vk.com/" target="_blank" rel="noreferrer">Открыть VK Ads</a><p className="mt-2 text-[11px] leading-5 text-indigo-200/45">Первая версия готовит текст, CTA и ссылки с tracking. Объявление запускается в кабинете рекламодателя; прямое управление VK Ads API добавляется после получения доступа к нему.</p></div><div className="mt-4 space-y-2 text-xs text-indigo-100/70"><p>• Используй контекстные и широкие, не чувствительные параметры аудитории.</p><p>• Не формируй сегменты по предполагаемым долгам или плохой кредитной истории конкретных людей.</p><p>• Реклама ведёт в диалог, который пользователь начинает сам.</p></div></article>
      <article className={panel+" p-5"}><h2 className="text-lg font-extrabold">Текстовый шаблон</h2><p className="mt-3 rounded-xl bg-white/[.035] p-4 text-sm leading-6 text-indigo-100/75">Нужен микрозайм? Посмотрите предложения четырёх микрофинансовых организаций. Некоторые кредиторы рассматривают заявки заёмщиков с разной кредитной историей. Ознакомьтесь с условиями и подайте заявку напрямую выбранной компании.</p><p className="mt-3 text-[11px] leading-5 text-amber-100/55">Не заявляй, что займ уже одобрен, если МФО не предоставила индивидуальное подтверждение. Рекламодатель, маркировка, условия и предупреждение должны быть проверены до размещения.</p></article>
    </section>}
  </main>;
}
