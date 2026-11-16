import { useState } from "react";
import { useLoad } from "../lib/useLoad";
import { fmtDateTime, rub } from "../lib/api";
import type { FriendsInfo } from "../lib/types";
import { Icon } from "../components/Icon";
import { EmptyState, ErrorState, ListSkeleton, PageHeader, SectionTitle } from "../components/ui";
import { haptic, hapticNotify, openExternal, showAlert } from "../lib/telegram";

export default function Friends() {
  const { data, error, reload } = useLoad<FriendsInfo>("/friends");
  const [copied, setCopied] = useState(false);

  async function copyLink() {
    if (!data) return;
    haptic("light");
    try {
      await navigator.clipboard.writeText(data.ref_link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      showAlert(`Твоя ссылка:\n${data.ref_link}`);
    }
  }

  return (
    <div>
      <PageHeader title="Друзья" subtitle="Приглашай и получай реальные бонусы" back="/" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!data && !error && <ListSkeleton rows={3} />}
      {data && (
        <>
          <section className="px-5">
            <div className="card-gold relative overflow-hidden p-5">
              <div className="absolute -right-8 -top-10 h-36 w-36 rounded-full bg-gold/10 blur-2xl" />
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gold/15 text-gold shadow-glow-gold">
                  <Icon name="gift" className="h-6 w-6" />
                </div>
                <div>
                  <div className="text-sm font-bold">+100 ₽ за друга</div>
                  <div className="text-xs text-indigo-300/75">после его первой выплаченной заявки</div>
                </div>
              </div>
              <div className="mt-4 rounded-2xl bg-navy-950/60 p-3">
                <div className="break-all text-xs leading-relaxed text-electric">{data.ref_link}</div>
              </div>
              <div className="mt-3 flex gap-2">
                <button className="btn-ghost flex-1" onClick={() => void copyLink()}>
                  <Icon name={copied ? "check" : "copy"} className="h-4 w-4" />
                  {copied ? "Скопировано" : "Копировать ссылку"}
                </button>
                <button
                  className="btn-gold flex-1"
                  onClick={() => {
                    hapticNotify("success");
                    openExternal(data.share_link);
                  }}
                >
                  <Icon name="share" className="h-4 w-4" /> Поделиться
                </button>
              </div>
            </div>
          </section>

          <section className="px-5 pt-4">
            <div className="card-glass p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-xs font-extrabold uppercase tracking-wider text-indigo-200">Как работает бонус</h2>
                <span className="rounded-full bg-gold/10 px-2.5 py-1 text-[10px] font-bold text-gold">+100 ₽</span>
              </div>
              <div className="space-y-3">
                {[
                  { n: "01", title: "Поделись ссылкой", text: "Друг регистрируется по твоей персональной ссылке." },
                  { n: "02", title: "Друг получает первую выплату", text: "Засчитывается только завершённая и реально выплаченная заявка." },
                  { n: "03", title: "Получай бонус", text: "BONVERA начисляет тебе 100 ₽ за квалифицированного друга." },
                ].map((step, index) => (
                  <div key={step.n} className="flex gap-3">
                    <div className="flex shrink-0 flex-col items-center">
                      <span className="flex h-8 w-8 items-center justify-center rounded-xl border border-electric/20 bg-electric/10 text-[11px] font-extrabold text-electric">{step.n}</span>
                      {index < 2 && <span className="mt-1 h-5 w-px bg-gradient-to-b from-electric/40 to-transparent" />}
                    </div>
                    <div className="min-w-0 pb-1">
                      <div className="text-xs font-bold text-white">{step.title}</div>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-indigo-300/65">{step.text}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="mt-4 grid grid-cols-2 gap-3 px-5">
            <div className="card-glass p-4 text-center">
              <div className="text-2xl font-extrabold text-electric">{data.invited}</div>
              <div className="mt-1 text-[12px] text-indigo-300/75">приглашено друзей</div>
              <div className="mt-2 text-[10px] text-indigo-300/45">по твоей ссылке</div>
            </div>
            <div className="card-glass p-4 text-center">
              <div className="text-2xl font-extrabold text-emerald-glow">{data.qualified}</div>
              <div className="mt-1 text-[12px] text-indigo-300/75">с первой выплатой</div>
              <div className="mt-2 text-[10px] text-indigo-300/45">квалифицированные</div>
            </div>
            <div className="card-glass p-4 text-center">
              <div className="text-xl font-extrabold text-gold-gradient">{rub(data.bonus_earned)}</div>
              <div className="mt-1 text-[12px] text-indigo-300/75">бонусы +100 ₽</div>
            </div>
            <div className="card-glass p-4 text-center">
              <div className="text-xl font-extrabold text-gold-gradient">{rub(data.referral_earned)}</div>
              <div className="mt-1 text-[12px] text-indigo-300/75">комиссия {data.ref_percent}%</div>
            </div>
          </section>

          <section className="px-5 pt-4">
            <div className="card-glass space-y-2.5 p-5 text-xs leading-relaxed text-indigo-200/70">
              <div className="flex gap-2">
                <Icon name="check" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-glow" />
                <span>
                  Бонус +100 ₽ начисляется только после того, как приглашённый друг получит первую
                  реальную выплату (статус «Выплачено»). Регистрация и клик по ссылке не считаются.
                </span>
              </div>
              <div className="flex gap-2">
                <Icon name="check" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-glow" />
                <span>
                  Дополнительно ты получаешь {data.ref_percent}% от кэшбэка подтверждённых заказов
                  друга — это отдельная реферальная комиссия, она не заменяет бонус +100 ₽.
                </span>
              </div>
              <div className="flex gap-2">
                <Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
                <span>
                  Самоприглашения и повторная привязка запрещены. Нарушения ведут к отмене бонусов и
                  блокировке.
                </span>
              </div>
            </div>
          </section>

          <SectionTitle>История начислений</SectionTitle>
          {data.history.length === 0 ? (
            <EmptyState
              icon="friends"
              title="Пока пусто"
              text="Пригласи первого друга — начисления появятся здесь после его первой выплаты."
            />
          ) : (
            <div className="space-y-2 px-5 pb-6">
              {data.history.map((e) => (
                <div key={e.id} className="card-glass flex items-center justify-between gap-3 p-4">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">{e.kind_ru}</div>
                    <div className="truncate text-[12px] text-indigo-300/70">{e.note}</div>
                    <div className="text-[12px] text-indigo-300/40">{fmtDateTime(e.created)}</div>
                  </div>
                  <div className="shrink-0 text-sm font-extrabold text-emerald-glow">+{rub(e.amount)}</div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}