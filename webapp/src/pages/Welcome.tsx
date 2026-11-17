import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";
import { markOnboarded } from "../lib/onboarding";
import { haptic, hapticNotify } from "../lib/telegram";

const LAST_STEP = 2;

const HOW_STEPS: { icon: IconName; title: string; text: string }[] = [
  {
    icon: "catalog",
    title: "Выбери оффер",
    text: "Карта, заём или другой продукт из каталога — с суммой награды и условиями.",
  },
  {
    icon: "share",
    title: "Оформи по ссылке",
    text: "Переходи к банку по партнёрской ссылке и оформляй на своих условиях.",
  },
  {
    icon: "camera",
    title: "Загрузи подтверждение",
    text: "Скриншот заявки или выписки. Лишние данные и номера счетов не нужны.",
  },
  {
    icon: "wallet",
    title: "Получи деньги",
    text: "Проверяем подтверждение — и награда падает на баланс.",
  },
];

const IMPORTANT: { icon: IconName; title: string; text: string }[] = [
  {
    icon: "clock",
    title: "Сроки — от 14 до 60 дней",
    text: "Столько банк проверяет условия, а мы — подтверждение. Раньше выплата не придёт.",
  },
  {
    icon: "shield",
    title: "Покупки и депозиты — своими деньгами",
    text: "Кэшбэк не оплачивает покупку. Тратишь только то, что готов потратить.",
  },
  {
    icon: "coin",
    title: "Выплата — от 300 ₽",
    text: "Меньше минимума не выводим: награды копятся на балансе, пока не наберётся сумма.",
  },
];

export default function Welcome() {
  const [step, setStep] = useState(0);
  const navigate = useNavigate();

  const finish = useCallback(() => {
    markOnboarded();
    hapticNotify("success");
    navigate("/catalog", { replace: true });
  }, [navigate]);

  const goNext = () => {
    if (step >= LAST_STEP) {
      finish();
      return;
    }
    haptic("light");
    setStep((s) => Math.min(LAST_STEP, s + 1));
  };

  const goBack = () => {
    if (step === 0) return;
    haptic("light");
    setStep((s) => Math.max(0, s - 1));
  };

  return (
    <div className="safe-top flex min-h-screen flex-col px-5 pb-8 pt-5">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-gold/40 bg-navy-900 shadow-glow-gold">
            <Icon name="crown" className="h-5 w-5 text-gold" />
          </div>
          <div>
            <div className="text-base font-extrabold tracking-[0.22em] text-gold-gradient">BONVERA</div>
            <div className="text-[12px] text-indigo-300/70">кэшбэк за карты и займы</div>
          </div>
        </div>
        <button
          type="button"
          onClick={finish}
          className="flex min-h-11 shrink-0 items-center rounded-full border border-royal/25 bg-navy-900/70 px-4 text-[13px] font-semibold text-indigo-200 transition-colors active:bg-navy-800"
        >
          Пропустить
        </button>
      </header>

      <div
        className="mt-6 flex items-center gap-2"
        role="progressbar"
        aria-label="Шаг онбординга"
        aria-valuemin={1}
        aria-valuemax={3}
        aria-valuenow={step + 1}
      >
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={`h-2 rounded-full transition-all duration-300 ${
              i === step
                ? "w-7 bg-gradient-to-r from-amber-glow to-gold shadow-glow-gold"
                : i < step
                  ? "w-2 bg-gold/45"
                  : "w-2 bg-indigo-400/25"
            }`}
          />
        ))}
        <span className="ml-auto text-[12px] font-semibold text-indigo-300/60">
          Шаг {step + 1} из 3
        </span>
      </div>

      <div className="mt-4 flex-1">
        {step === 0 && (
          <>
            <section className="card-gold relative overflow-hidden p-6 text-center">
              <div className="pointer-events-none absolute -right-10 -top-12 h-40 w-40 rounded-full bg-gold/10 blur-3xl" />
              <div className="pointer-events-none absolute -bottom-16 -left-10 h-40 w-40 rounded-full bg-electric/10 blur-3xl" />
              <div className="relative mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-gold/40 bg-navy-950/70 shadow-glow-gold">
                <Icon name="crown" className="h-8 w-8 text-gold" />
              </div>
              <div className="relative mt-4 text-[10px] font-extrabold uppercase tracking-[0.2em] text-gold/75">
                Шаг 1 · Что это
              </div>
              <h1 className="relative mt-2 text-[26px] font-extrabold leading-tight">
                Тебе платят за то,{" "}
                <span className="text-gold-gradient">что ты и так оформляешь</span>
              </h1>
              <p className="relative mt-3 text-sm leading-relaxed text-indigo-200/80">
                Карты и займы ты оформляешь и без нас. BONVERA возвращает за это деньги: банк платит
                нам за клиента, мы делимся с тобой.
              </p>
            </section>
            <div className="mt-3 grid grid-cols-3 gap-2">
              {[
                { icon: "catalog" as IconName, label: "Карты" },
                { icon: "coin" as IconName, label: "Займы" },
                { icon: "wallet" as IconName, label: "На карту" },
              ].map((chip) => (
                <div
                  key={chip.label}
                  className="card-glass flex flex-col items-center gap-1.5 px-2 py-3 text-[12px] font-semibold text-indigo-200/85"
                >
                  <Icon name={chip.icon} className="h-5 w-5 text-electric" />
                  {chip.label}
                </div>
              ))}
            </div>
            <p className="mt-3 px-1 text-center text-[12px] leading-relaxed text-indigo-300/60">
              Без вложений и без риска: максимум, что ты тратишь, — несколько минут.
            </p>
          </>
        )}

        {step === 1 && (
          <>
            <section className="px-1">
              <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-electric/80">
                Шаг 2 · Как это работает
              </div>
              <h1 className="mt-2 text-[24px] font-extrabold leading-tight">
                Четыре шага до <span className="text-electric-gradient">выплаты</span>
              </h1>
            </section>
            <section className="card-glass mt-4 space-y-1 p-3">
              {HOW_STEPS.map((item, i) => (
                <div key={item.title} className="flex items-start gap-3 rounded-2xl p-3">
                  <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-electric/12 text-electric">
                    <Icon name={item.icon} className="h-5 w-5" />
                    <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-navy-950 text-[10px] font-extrabold text-gold">
                      {i + 1}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <div className="text-[14px] font-bold leading-tight">{item.title}</div>
                    <div className="mt-0.5 text-[12px] leading-relaxed text-indigo-300/70">
                      {item.text}
                    </div>
                  </div>
                </div>
              ))}
            </section>
            <p className="mt-3 flex items-start gap-2 px-1 text-[12px] leading-relaxed text-indigo-300/60">
              <Icon name="clock" className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
              Обычно оформление занимает 5–10 минут, проверка — дольше, чем кажется.
            </p>
          </>
        )}

        {step === 2 && (
          <>
            <section className="px-1">
              <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-gold/80">
                Шаг 3 · Важное
              </div>
              <h1 className="mt-2 text-[24px] font-extrabold leading-tight">
                Что знать <span className="text-gold-gradient">заранее</span>
              </h1>
            </section>
            <section className="mt-4 space-y-3">
              {IMPORTANT.map((item) => (
                <div key={item.title} className="card-glass flex items-start gap-3 p-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gold/12 text-gold">
                    <Icon name={item.icon} className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-[14px] font-bold leading-tight">{item.title}</div>
                    <div className="mt-1 text-[12px] leading-relaxed text-indigo-300/70">
                      {item.text}
                    </div>
                  </div>
                </div>
              ))}
            </section>
            <p className="mt-3 flex items-start gap-2 px-1 text-[12px] leading-relaxed text-indigo-300/60">
              <Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-electric" />
              Если условия оффера не выполнены, выплаты не будет. Это проверка, а не штраф — и мы
              скажем причину.
            </p>
          </>
        )}
      </div>

      <div className="mt-6 space-y-2.5">
        <button
          type="button"
          onClick={goNext}
          className="btn-gold min-h-[54px] w-full text-base"
        >
          {step === LAST_STEP ? "Поехали" : "Дальше"}
          <Icon name={step === LAST_STEP ? "catalog" : "chevron-right"} className="h-5 w-5" />
        </button>
        {step > 0 && (
          <button type="button" onClick={goBack} className="btn-ghost min-h-[48px] w-full">
            <Icon name="chevron-left" className="h-4 w-4" /> Назад
          </button>
        )}
      </div>
    </div>
  );
}
