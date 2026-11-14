import { useState } from "react";
import { useLoad } from "../lib/useLoad";
import type { MetaInfo } from "../lib/types";
import { Icon } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader, SectionTitle } from "../components/ui";
import { haptic, openExternal } from "../lib/telegram";

const FAQ: Array<{ q: string; a: string }> = [
  {
    q: "Как вывести деньги?",
    a: "Накопи минимальную сумму на доступном балансе, укажи банк и телефон СБП в настройках и создай заявку на вывод. Администратор проверит её и выполнит перевод вручную. Это не мгновенный автоматический вывод.",
  },
  {
    q: "Что такое холд?",
    a: "Холд — это период, в течение которого партнёрская сеть подтверждает выполненное условие (например, что покупка не возвращена). После холда и проверки заявка подтверждается, а награда становится доступна к выводу.",
  },
  {
    q: "Почему у предложения нет кнопки оформления?",
    a: "У части предложений ещё нет проверенной партнёрской ссылки или одобрения сети. Мы показываем их в каталоге, но не выдумываем ссылки: оформление откроется, когда администратор добавит подтверждённую ссылку.",
  },
  {
    q: "Когда начисляются бонусы?",
    a: "+20 ₽ — после подтверждённой подписки на канал; +10 ₽ — за первый подтверждённый заказ; +500 ₽ — за 10-й подтверждённый заказ; +100 ₽ — после первой реальной выплаты приглашённого друга. Каждый бонус начисляется один раз.",
  },
  {
    q: "Заявку отклонили. Что делать?",
    a: "Открой заявку и посмотри причину в истории. Если условие не выполнено или подтверждения не подошли, можно оформить предложение заново, если это разрешено правилами. Спорные ситуации решает поддержка.",
  },
  {
    q: "Какие файлы можно загружать?",
    a: "Скриншоты и фото выполненных условий (JPG, PNG, WebP, HEIC) и PDF до 10 МБ. Никогда не загружай паспортные сканы, CVV/CVC, PIN-коды, пароли, коды из SMS и полные номера карт.",
  },
];

export default function Support() {
  const { data: meta, error, reload } = useLoad<MetaInfo>("/meta");
  const [open, setOpen] = useState<number | null>(null);

  const contactUrl = meta?.support_url ?? (meta?.bot_username ? `https://t.me/${meta.bot_username}` : null);

  return (
    <div>
      <PageHeader title="Поддержка" subtitle="Ответы на частые вопросы" back="/profile" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!meta && !error && <ListSkeleton rows={2} />}

      <section className="space-y-2 px-5">
        {FAQ.map((f, i) => (
          <div key={i} className="card-glass overflow-hidden">
            <button
              className="flex w-full items-center justify-between gap-3 p-4 text-left"
              onClick={() => {
                haptic("light");
                setOpen(open === i ? null : i);
              }}
              aria-expanded={open === i}
            >
              <span className="text-sm font-bold">{f.q}</span>
              <Icon
                name="chevron-right"
                className={`h-4 w-4 shrink-0 text-indigo-300/50 transition-transform ${open === i ? "rotate-90" : ""}`}
              />
            </button>
            {open === i && (
              <p className="px-4 pb-4 text-xs leading-relaxed text-indigo-200/65">{f.a}</p>
            )}
          </div>
        ))}
      </section>

      {meta && (
        <>
          <SectionTitle>Связаться с нами</SectionTitle>
          <section className="px-5 pb-8">
            {contactUrl ? (
              <button className="btn-primary w-full" onClick={() => openExternal(contactUrl)}>
                <Icon name="support" className="h-4 w-4" /> Написать в поддержку
              </button>
            ) : (
              <div className="card-glass p-4 text-xs leading-relaxed text-indigo-200/65">
                Контакт поддержки пока не настроен администратором. По вопросам заявок и выплат пиши в
                чат бота в Telegram.
              </div>
            )}
            <p className="mt-3 text-[11px] leading-relaxed text-indigo-300/50">
              Поддержка не запрашивает пароли, коды из SMS и данные карт. Если кто-то просит их от имени
              BONVERA — это мошенники.
            </p>
          </section>
        </>
      )}
    </div>
  );
}