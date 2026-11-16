import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../src/", import.meta.url);
const read = (path) => readFile(new URL(path, root), "utf8");

test("web admin has standalone browser login with Telegram signed auth", async () => {
  const app = await read("App.tsx");
  const login = await read("pages/AdminLogin.tsx");
  assert.match(app, /\/admin\/login/);
  assert.match(login, /telegram-widget\.js/);
  assert.match(login, /auth\/telegram-widget/);
  assert.match(login, /setSession/);
});

test("admin workspace exposes operational sections and server-backed actions", async () => {
  const admin = await read("pages/Admin.tsx");
  for (const label of ["Пользователи", "Заявки", "Выплаты", "Офферы", "Рассылки", "Финансы"]) assert.ok(admin.includes(label));
  assert.match(admin, /admin\/offers\/.*enabled/);
  assert.match(admin, /admin\/payouts\/.*action/);
  assert.match(admin, /window\.confirm/);
});

test("server admin login is restricted to allowlisted IDs and bookmaker approval", async () => {
  const api = await readFile(new URL("../../bot/tma_api.py", import.meta.url), "utf8");
  const auth = await readFile(new URL("../../bot/tma_auth.py", import.meta.url), "utf8");
  assert.match(api, /uid not in cfg\.admins/);
  assert.match(api, /bookmaker_not_approved/);
  assert.match(auth, /verify_telegram_login/);
  assert.match(auth, /auth_date > 600/);
});
