import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { closeVite, loadModule } from "./harness.mjs";

/** Minimal semantic version compare for Bot API level checks. */
function versionAtLeast(current, required) {
  const parse = (v) => v.split(".").map((n) => Number.parseInt(n, 10) || 0);
  const a = parse(current);
  const b = parse(required);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const left = a[i] ?? 0;
    const right = b[i] ?? 0;
    if (left !== right) return left > right;
  }
  return true;
}

const calls = [];
function record(name, payload) {
  calls.push({ name, payload });
}

const webapp = {
  initData: "query_id=AAE&user=%7B%22id%22%3A1%7D&auth_date=1&hash=deadbeef",
  initDataUnsafe: { user: { id: 1, first_name: "Test", username: "tester" } },
  version: "7.10",
  platform: "android",
  colorScheme: "dark",
  themeParams: {},
  isExpanded: true,
  viewportHeight: 800,
  viewportStableHeight: 800,
  ready: () => record("ready"),
  expand: () => record("expand"),
  close: () => record("close"),
  setHeaderColor: (c) => record("setHeaderColor", c),
  setBackgroundColor: (c) => record("setBackgroundColor", c),
  setBottomBarColor: (c) => record("setBottomBarColor", c),
  requestFullscreen: () => record("requestFullscreen"),
  isVersionAtLeast: (v) => versionAtLeast("7.10", v),
  openLink: (u) => record("openLink", u),
  openTelegramLink: (u) => record("openTelegramLink", u),
  sendData: () => record("sendData"),
  showAlert: (m) => record("showAlert", m),
  showConfirm: (m, cb) => {
    record("showConfirm", m);
    cb(false);
  },
  HapticFeedback: {
    impactOccurred: (s) => record("haptic", s),
    notificationOccurred: (t) => record("hapticNotify", t),
    selectionChanged: () => record("hapticSelect"),
  },
  BackButton: { show: () => record("backShow"), hide: () => record("backHide"), onClick: () => {}, offClick: () => {} },
  onEvent: () => {},
  offEvent: () => {},
};

globalThis.window.Telegram = { WebApp: webapp };

let tg;

before(async () => {
  tg = await loadModule("/src/lib/telegram.ts");
});

after(async () => {
  await closeVite();
});

test("prepares the WebView: ready, expand and the dark theme colors", () => {
  calls.length = 0;

  tg.initTelegram();

  const names = calls.map((c) => c.name);
  assert.ok(names.includes("ready"));
  assert.ok(names.includes("expand"));
  const header = calls.find((c) => c.name === "setHeaderColor");
  assert.equal(header.payload, "#05070f");
  const background = calls.find((c) => c.name === "setBackgroundColor");
  assert.equal(background.payload, "#05070f");
});

test("requests fullscreen only on clients that support it", () => {
  calls.length = 0;

  tg.initTelegram();

  assert.equal(
    calls.some((c) => c.name === "requestFullscreen"),
    false,
    "на клиенте 7.10 полноэкранный режим не запрашивается",
  );
});

test("uses the native alert on a modern client", () => {
  calls.length = 0;

  tg.showAlert("Готово");

  assert.ok(calls.some((c) => c.name === "showAlert" && c.payload === "Готово"));
});

test("falls back to window.alert on a client older than Bot API 6.2", () => {
  calls.length = 0;
  const original = webapp.isVersionAtLeast;
  webapp.isVersionAtLeast = (v) => versionAtLeast("5.0", v);
  const alerts = [];
  globalThis.window.alert = (m) => alerts.push(m);

  tg.showAlert("Готово");

  webapp.isVersionAtLeast = original;
  assert.deepEqual(alerts, ["Готово"]);
  assert.equal(
    calls.some((c) => c.name === "showAlert"),
    false,
    "нативный диалог не вызывается на старом клиенте",
  );
});

test("resolves the native confirm with the user choice", async () => {
  calls.length = 0;

  const result = await tg.showConfirm("Отменить?");

  assert.equal(result, false);
  assert.ok(calls.some((c) => c.name === "showConfirm"));
});

test("falls back to window.confirm on an old client", async () => {
  const original = webapp.isVersionAtLeast;
  webapp.isVersionAtLeast = (v) => versionAtLeast("5.0", v);
  const asked = [];
  globalThis.window.confirm = (m) => {
    asked.push(m);
    return true;
  };

  const result = await tg.showConfirm("Отменить?");

  webapp.isVersionAtLeast = original;
  assert.equal(result, true);
  assert.deepEqual(asked, ["Отменить?"]);
});

test("opens t.me links through the Telegram client and other links externally", () => {
  calls.length = 0;

  tg.openExternal("https://t.me/bonvera");
  tg.openExternal("https://example.com/rules");

  assert.ok(calls.some((c) => c.name === "openTelegramLink" && c.payload === "https://t.me/bonvera"));
  assert.ok(calls.some((c) => c.name === "openLink" && c.payload === "https://example.com/rules"));
});

test("exposes the raw initData and the unsigned hint separately", () => {
  assert.equal(tg.rawInitData(), webapp.initData);
  assert.equal(tg.tgUserHint().username, "tester");
});
