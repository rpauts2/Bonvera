import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { closeVite, loadModule, render, renderPage, renderPageAsUser } from "./harness.mjs";

/** Every route of the Mini App with the marker its header must contain. */
const ROUTES = [
  ["/src/pages/Home.tsx", "/", "BONVERA"],
  ["/src/pages/Tasks.tsx", "/tasks", "Задания"],
  ["/src/pages/Catalog.tsx", "/catalog", "Каталог"],
  ["/src/pages/Friends.tsx", "/friends", "Друзья"],
  ["/src/pages/Profile.tsx", "/profile", "Профиль"],
  ["/src/pages/Wallet.tsx", "/wallet", "Кошелёк"],
  ["/src/pages/OfferPage.tsx", "/offer/11", "Предложение"],
  ["/src/pages/MyApps.tsx", "/apps", "Мои заявки"],
  ["/src/pages/AppDetail.tsx", "/apps/5", "Заявка"],
  ["/src/pages/History.tsx", "/history", "История операций"],
  ["/src/pages/Withdraw.tsx", "/withdraw", "Вывод средств"],
  ["/src/pages/Achievements.tsx", "/achievements", "Достижения"],
  ["/src/pages/Leaderboard.tsx", "/leaderboard", "Рейтинг"],
  ["/src/pages/Settings.tsx", "/settings", "Настройки СБП"],
  ["/src/pages/Notifications.tsx", "/notifications", "Уведомления"],
  ["/src/pages/Support.tsx", "/support", "Поддержка"],
  ["/src/pages/Rules.tsx", "/rules", "Правила сервиса"],
];

after(async () => {
  await closeVite();
});

test("the app shell renders the boot screen while the session is being resolved", async () => {
  const App = (await loadModule("/src/App.tsx")).default;

  const html = await render(
    React.createElement(
      MemoryRouter,
      { initialEntries: ["/"] },
      React.createElement(App),
    ),
  );

  assert.ok(html.includes("BONVERA"), "загрузочный экран показывает логотип BONVERA");
  assert.ok(html.includes("skeleton"), "загрузочный экран показывает скелетон");
});

test("the bottom navigation exposes exactly the five main sections", async () => {
  const { TabBar } = await loadModule("/src/components/TabBar.tsx");

  const html = await render(
    React.createElement(MemoryRouter, { initialEntries: ["/"] }, React.createElement(TabBar)),
  );

  for (const label of ["Главная", "Задания", "Каталог", "Друзья", "Профиль"]) {
    assert.ok(html.includes(`>${label}<`), `вкладка «${label}» присутствует в нижней навигации`);
  }
  const links = html.match(/<a /g) ?? [];
  assert.equal(links.length, 5);
});

test("the bottom navigation respects the Telegram safe area", async () => {
  const { TabBar } = await loadModule("/src/components/TabBar.tsx");

  const html = await render(
    React.createElement(MemoryRouter, { initialEntries: ["/"] }, React.createElement(TabBar)),
  );

  assert.ok(html.includes("safe-area-inset-bottom"), "нижняя панель учитывает safe area Telegram");
});

for (const [file, path, marker] of ROUTES) {
  test(`route ${path} renders its own screen (${file.split("/").pop()})`, async () => {
    const html = await renderPageAsUser(file, { path });
    assert.ok(html.length > 0, "страница отрендерилась");
    assert.ok(html.includes(marker), `на странице есть заголовок «${marker}»`);
  });
}

test("the profile screen shows the user and the real menu entries", async () => {
  const html = await renderPageAsUser("/src/pages/Profile.tsx", { path: "/profile" });

  assert.ok(html.includes("Тестер"));
  assert.ok(html.includes("@tester"));
  assert.ok(html.includes("Уровень 2"));
  for (const entry of ["Кошелёк", "Мои заявки", "История операций", "Достижения", "Рейтинг"]) {
    assert.ok(html.includes(entry), `в меню профиля есть «${entry}»`);
  }
});

test("the profile screen stays empty for an anonymous visitor", async () => {
  const html = await renderPage("/src/pages/Profile.tsx", { path: "/profile" });
  assert.equal(html, "");
});

test("inner pages do not repeat the bottom navigation", async () => {
  const html = await renderPage("/src/pages/Wallet.tsx", { path: "/wallet" });
  assert.equal(html.includes("safe-area-inset-bottom"), false);
});
