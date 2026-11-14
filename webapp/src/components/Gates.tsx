import { useState } from "react";
import { useSession } from "../state/session";
import { Icon } from "./Icon";
import { rawInitData } from "../lib/telegram";

export function BootScreen() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-5">
      <div className="relative">
        <div className="absolute inset-0 animate-pulse-glow rounded-full bg-royal/40 blur-2xl" />
        <div className="relative flex h-20 w-20 items-center justify-center rounded-3xl border border-gold/40 bg-navy-900 shadow-glow-gold">
          <Icon name="crown" className="h-10 w-10 text-gold" />
        </div>
      </div>
      <div className="text-xl font-extrabold tracking-[0.3em] text-gold-gradient">BONVERA</div>
      <div className="skeleton h-2 w-40" />
    </div>
  );
}

export function ErrorScreen({ message }: { message: string }) {
  const { login } = useSession();
  const [devData, setDevData] = useState("");
  const isDev = import.meta.env.DEV && !rawInitData();

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-8 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-rose-alert/40 bg-navy-900">
        <Icon name="shield" className="h-8 w-8 text-rose-alert" />
      </div>
      <h1 className="text-lg font-bold">Не удалось войти</h1>
      <p className="text-sm leading-relaxed text-indigo-200/70">{message}</p>
      <button className="btn-primary" onClick={() => void login()}>
        <Icon name="refresh" className="h-4 w-4" /> Попробовать снова
      </button>
      {isDev && (
        <div className="mt-6 w-full max-w-sm space-y-2 text-left">
          <p className="text-xs text-indigo-300/60">
            DEV: вставь initData, сгенерированный scripts/dev_initdata.py
          </p>
          <textarea
            className="input-dark h-24 text-xs"
            value={devData}
            onChange={(e) => setDevData(e.target.value)}
            placeholder="query_id=...&user=...&auth_date=...&hash=..."
          />
          <button className="btn-ghost w-full" onClick={() => void login(devData)}>
            Войти с этим initData
          </button>
        </div>
      )}
    </div>
  );
}

export function AcceptGate() {
  const { acceptRules } = useSession();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const accept = async () => {
    setBusy(true);
    setErr(null);
    try {
      await acceptRules();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ошибка. Попробуй ещё раз.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl border border-gold/40 bg-navy-900 shadow-glow-gold">
        <Icon name="crown" className="h-10 w-10 text-gold" />
      </div>
      <div>
        <h1 className="text-2xl font-extrabold">Добро пожаловать в BONVERA</h1>
        <p className="mt-3 text-sm leading-relaxed text-indigo-200/70">
          Финансовая платформа с наградами за реальные действия. Чтобы продолжить,
          подтверди, что тебе исполнилось 18 лет, и прими правила сервиса.
        </p>
      </div>
      <div className="card-glass w-full space-y-3 p-5 text-left text-sm text-indigo-200/80">
        <div className="flex gap-3">
          <Icon name="shield" className="h-5 w-5 shrink-0 text-electric" />
          Вознаграждения начисляются только после проверки выполненных условий.
        </div>
        <div className="flex gap-3">
          <Icon name="doc" className="h-5 w-5 shrink-0 text-electric" />
          Займы и ставки — не способ заработка; соблюдай ограничения 18+/21+.
        </div>
        <div className="flex gap-3">
          <Icon name="lock" className="h-5 w-5 shrink-0 text-electric" />
          Никогда не передавай паспортные данные, CVV, PIN и SMS-коды.
        </div>
      </div>
      {err && <p className="text-sm text-rose-alert">{err}</p>}
      <button className="btn-gold w-full" disabled={busy} onClick={() => void accept()}>
        <Icon name="check" className="h-5 w-5" /> Принимаю правила, мне 18+
      </button>
    </div>
  );
}