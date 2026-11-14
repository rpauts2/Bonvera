import { after, test } from "node:test";
import assert from "node:assert/strict";
import {
  achievementStub,
  closeVite,
  dashboardStub,
  eventStub,
  offerStub,
  renderPageAsUser,
} from "./harness.mjs";

after(async () => {
  await closeVite();
});

/** Render the home screen with a prepared dashboard payload. */
async function renderHome(dashboard) {
  return renderPageAsUser("/src/pages/Home.tsx", {
    path: "/",
    props: { initialData: dashboard },
  });
}

test("the home screen invites to earn when the balance is below the minimum", async () => {
  const html = await renderHome(dashboardStub());

  assert.ok(html.includes("Как заработать</a>"), "нужен призыв перейти в каталог");
  assert.ok(html.includes("Минимум вывода — 300 ₽"), "указан минимальная сумма вывода");
  assert.equal(html.includes("Вывести</a>"), false, "кнопка вывода скрыта при малом балансе");
  assert.ok(
    html.includes("Пока нет активных заявок и выплат."),
    "честный текст вместо пустых плиток",
  );
});

test("the home screen offers a withdrawal when the balance is enough", async () => {
  const html = await renderHome(
    dashboardStub({
      wallet: { ...dashboardStub().wallet, available: 1200, paid_total: 4500 },
    }),
  );

  assert.ok(html.includes("Вывести</a>"), "кнопка вывода доступна");
  assert.equal(html.includes("Как заработать</a>"), false, "CTA заработка не нужен при достаточном балансе");
  assert.ok(html.includes("Всего выплачено"), "показаны накопленные выплаты");
});

test("the home screen shows popular offers with an honest badge", async () => {
  const html = await renderHome(
    dashboardStub({
      popular_offers: [
        offerStub({ id: 11, code: "tst_ok", name: "Карта Тест" }),
        offerStub({
          id: 12,
          code: "tst_nolink",
          name: "Карта без ссылки",
          available: false,
          has_partner_link: false,
          unavailable_reason: "Партнёрская ссылка ещё не добавлена.",
        }),
      ],
    }),
  );

  assert.ok(html.includes("Популярные предложения"));
  assert.ok(html.includes("Карта Тест"), "доступный оффер показан");
  assert.ok(html.includes("Карта без ссылки"), "оффер без ссылки тоже показан");
  assert.ok(html.includes("Нет ссылки"), "у оффера без ссылки честный бейдж");
});

test("the home screen explains an empty popular list instead of showing a blank block", async () => {
  const html = await renderHome(dashboardStub({ popular_offers: [] }));

  assert.ok(html.includes("Каталог обновляется"), "пустое состояние объяснено");
  assert.ok(html.includes("Открыть каталог"), "есть действие, ведущее в каталог");
});

test("the home screen shows the referral link and a growth call to action", async () => {
  const html = await renderHome(dashboardStub());

  assert.ok(html.includes("+100 ₽ за друга"), "блок приглашения друга на месте");
  assert.ok(html.includes("https://t.me/bonvera_test_bot?start=ref_1"), "реферальная ссылка показана");
  assert.ok(html.includes("Копировать"), "ссылку можно скопировать");
});

test("the home screen advertises the channel only when it is configured", async () => {
  const without = await renderHome(dashboardStub({ channel_url: null }));
  assert.equal(without.includes("Подпишись на канал BONVERA"), false);

  const with_ = await renderHome(dashboardStub({ channel_url: "https://t.me/bonvera_channel" }));
  assert.ok(with_.includes("Подпишись на канал BONVERA"));
  assert.ok(with_.includes("+20 ₽ за подтверждённую подписку"));
});

test("the home screen lists the latest events", async () => {
  const empty = await renderHome(dashboardStub({ recent_events: [] }));
  assert.equal(empty.includes("Последние события"), false, "пустой блок событий не показывается");

  const html = await renderHome(
    dashboardStub({
      recent_events: [
        eventStub({ id: "deal:1", title: "Заявка #12", text: "Заявка взята в работу" }),
        eventStub({ id: "payout:2", kind: "payout", title: "Вывод #3", text: "Выплата отправлена" }),
      ],
    }),
  );

  assert.ok(html.includes("Последние события"));
  assert.ok(html.includes("Заявка #12"));
  assert.ok(html.includes("Выплата отправлена"));
});

test("the home screen shows the next goal instead of an achievements grid", async () => {
  const html = await renderHome(
    dashboardStub({
      achievements_preview: [
        achievementStub({ title: "Первое предложение", description: "Оформи предложение и получи +10 ₽" }),
        achievementStub({ key: "ten", title: "Десять заказов", unlocked: true }),
      ],
    }),
  );

  assert.ok(html.includes("Ближайшая цель"));
  assert.ok(html.includes("Первое предложение"), "показана ближайшая незакрытая цель");
  assert.equal(html.includes("Десять заказов"), false, "закрытые достижения не занимают место цели");
});

test("the home screen confirms that every goal is reached", async () => {
  const html = await renderHome(
    dashboardStub({
      achievements_preview: [achievementStub({ title: "Первое предложение", unlocked: true })],
    }),
  );

  assert.ok(html.includes("Все достижения получены"));
});

test("the home screen asks for a first order while there is no confirmed one", async () => {
  const html = await renderHome(dashboardStub({ confirmed_orders: 0 }));

  assert.ok(html.includes("Оформи первое предложение и получи +10 ₽"));
  assert.ok(html.includes("0/10"), "прогресс бонуса за 10 заказов виден");
});

test("the home screen links to the rules as a trust block", async () => {
  const html = await renderHome(dashboardStub());

  assert.ok(html.includes('href="/rules"'), "блок доверия ведёт на правила");
  assert.ok(html.includes("Награды начисляются только после проверки"), "условия выплат объяснены");
});
