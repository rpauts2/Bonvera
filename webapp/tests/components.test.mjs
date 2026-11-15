import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { closeVite, loadModule, offerStub, render } from "./harness.mjs";

before(async () => {
  await loadModule("/src/components/ui.tsx");
});

after(async () => {
  await closeVite();
});

test("an offer card shows brand, product, reward and hold of a real offer", async () => {
  const { OfferCard } = await loadModule("/src/components/OfferCard.tsx");

  const html = await render(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(OfferCard, { offer: offerStub() }),
    ),
  );

  assert.ok(html.includes("Кредитная карта Тест"));
  assert.ok(html.includes("Тест Банк"));
  assert.ok(html.includes("500"));
  assert.ok(html.includes("холд 14 дн."));
  assert.ok(html.includes("Карты"), "категория оффера подписана");
  assert.ok(html.includes("/offer/11"), "карточка ведёт на страницу предложения");
  assert.ok(html.includes("aspect-video"), "банковская композиция показывается целиком в формате 16:9");
});

test("an offer without a partner link is labelled instead of hidden", async () => {
  const { OfferCard } = await loadModule("/src/components/OfferCard.tsx");

  const html = await render(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(OfferCard, {
        offer: offerStub({ available: false, has_partner_link: false }),
      }),
    ),
  );

  assert.ok(html.includes("Нет ссылки"));
});

test("the empty state explains what to do instead of showing a blank screen", async () => {
  const { EmptyState } = await loadModule("/src/components/ui.tsx");

  const html = await render(
    React.createElement(EmptyState, {
      icon: "search",
      title: "Ничего не найдено",
      text: "Попробуй изменить запрос или фильтры.",
    }),
  );

  assert.ok(html.includes("Ничего не найдено"));
  assert.ok(html.includes("Попробуй изменить запрос или фильтры."));
});

test("the error state shows the server message and a retry action", async () => {
  const { ErrorState } = await loadModule("/src/components/ui.tsx");

  const html = await render(
    React.createElement(ErrorState, { message: "Каталог недоступен", onRetry: () => {} }),
  );

  assert.ok(html.includes("Каталог недоступен"));
  assert.ok(html.includes("Повторить"));
});

test("the status badge maps every backend status to a human label", async () => {
  const { StatusBadge } = await loadModule("/src/components/ui.tsx");

  const cases = [
    ["new", "Оформляешь"],
    ["proof", "На проверке"],
    ["hold", "Холд"],
    ["confirmed", "Подтверждено"],
    ["paid", "Выплачено"],
    ["rejected", "Отклонено"],
    ["expired", "Истекло"],
  ];

  for (const [status, label] of cases) {
    const html = await render(React.createElement(StatusBadge, { status }));
    assert.ok(html.includes(label), `статус ${status} подписан как «${label}»`);
  }
});

test("the safe-area and responsive helpers are defined in the stylesheet", async () => {
  const { readFile } = await import("node:fs/promises");
  const path = await import("node:path");
  const { projectRoot } = await import("./harness.mjs");

  const css = await readFile(path.join(projectRoot, "src/index.css"), "utf8");

  assert.ok(css.includes("safe-area-inset-top"), "верхний safe area учтён");
  assert.ok(css.includes("safe-area-inset-bottom"), "нижний safe area учтён");
  assert.ok(css.includes("overscroll-behavior-y: none"), "отскок страницы отключён");
  assert.ok(css.includes("min-height: 100vh"), "приложение занимает весь экран");
});
