import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useLoad } from "../lib/useLoad";
import type { TaskState } from "../lib/types";
import { Icon, type IconName } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader, ProgressBar } from "../components/ui";
import { haptic, hapticNotify, openExternal, showAlert } from "../lib/telegram";

const TASK_ICON: Record<string, IconName> = {
  channel: "bell",
  referral: "friends",
  first_order: "star",
  ten_orders: "chest",
};

export default function Tasks() {
  const { data, error, reload, setData } = useLoad<TaskState[]>("/tasks");
  const [checking, setChecking] = useState(false);

  async function checkChannel() {
    setChecking(true);
    try {
      const updated = await api.post<TaskState>("/tasks/channel/check");
      setData((prev) => (prev ? prev.map((t) => (t.key === "channel" ? updated : t)) : prev));
      if (updated.done) {
        hapticNotify("success");
        showAlert("Подписка подтверждена! +20 ₽ зачислены в кошелёк.");
      } else {
        hapticNotify("warning");
        showAlert(updated.hint ?? "Подписка не найдена. Подпишись на канал и проверь ещё раз.");
      }
    } catch (e) {
      hapticNotify("error");
      showAlert(e instanceof Error ? e.message : "Не удалось проверить подписку.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div>
      <PageHeader title="Задания" subtitle="Реальные бонусы за реальные действия" back="/" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!data && !error && <ListSkeleton rows={4} />}
      {data && (
        <div className="space-y-3 px-5 pb-6">
          {data.map((t) => (
            <div key={t.key} className={`card-glass p-5 ${t.done ? "border-emerald-glow/30" : ""}`}>
              <div className="flex items-start gap-3">
                <div
                  className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${
                    t.done ? "bg-emerald-glow/15 text-emerald-glow" : "bg-royal/20 text-royal-soft"
                  }`}
                >
                  <Icon name={t.done ? "check" : TASK_ICON[t.key] ?? "spark"} className="h-6 w-6" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-bold">{t.title}</div>
                    <div className="shrink-0 text-base font-extrabold text-gold-gradient">+{t.reward} ₽</div>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-indigo-200/60">{t.description}</p>
                </div>
              </div>

              {t.target > 1 && (
                <div className="mt-3">
                  <div className="mb-1.5 flex justify-between text-[11px] text-indigo-300/60">
                    <span>Прогресс</span>
                    <span className="font-bold text-electric">
                      {Math.min(t.progress, t.target)}/{t.target}
                    </span>
                  </div>
                  <ProgressBar value={t.progress} max={t.target} gold={t.done} />
                </div>
              )}

              {t.hint && <p className="mt-3 text-[11px] leading-relaxed text-gold/80">{t.hint}</p>}

              <div className="mt-4">
                {t.done ? (
                  <div className="flex items-center gap-2 rounded-2xl bg-emerald-glow/10 px-4 py-3 text-sm font-bold text-emerald-glow">
                    <Icon name="check" className="h-4 w-4" /> Бонус получен
                  </div>
                ) : t.action === "check_subscription" ? (
                  <div className="flex gap-2">
                    {t.channel_url && (
                      <button className="btn-ghost flex-1" onClick={() => openExternal(t.channel_url!)}>
                        <Icon name="share" className="h-4 w-4" /> Канал
                      </button>
                    )}
                    <button
                      className="btn-primary flex-1"
                      disabled={checking || !t.channel_url}
                      onClick={() => {
                        haptic("medium");
                        void checkChannel();
                      }}
                    >
                      <Icon name="refresh" className={`h-4 w-4 ${checking ? "animate-spin" : ""}`} />
                      {checking ? "Проверяю…" : "Проверить"}
                    </button>
                  </div>
                ) : t.action === "invite" ? (
                  <Link to="/friends" className="btn-primary w-full" onClick={() => haptic("light")}>
                    <Icon name="friends" className="h-4 w-4" /> Пригласить друга
                  </Link>
                ) : (
                  <Link to="/catalog" className="btn-primary w-full" onClick={() => haptic("light")}>
                    <Icon name="catalog" className="h-4 w-4" /> К предложениям
                  </Link>
                )}
              </div>
            </div>
          ))}
          <p className="px-1 pt-2 text-[11px] leading-relaxed text-indigo-300/50">
            Бонусы зачисляются в реальный баланс кошелька один раз. Повторные проверки и клики не дают
            повторных начислений. Задания не обновляются ежедневно — это постоянные достижения.
          </p>
        </div>
      )}
    </div>
  );
}