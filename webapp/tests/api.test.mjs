import { after, before, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { closeVite, jsonResponse, loadModule, mockFetch } from "./harness.mjs";

let api;
let apiModule;

before(async () => {
  apiModule = await loadModule("/src/lib/api.ts");
  api = apiModule.api;
});

after(async () => {
  await closeVite();
});

beforeEach(() => {
  apiModule.setSession(null);
});

test("unwraps the data envelope of a successful response", async () => {
  const fetchMock = mockFetch({ "/me": { id: 7 } });

  const data = await api.get("/me");

  assert.deepEqual(data, { id: 7 });
  assert.equal(fetchMock.calls[0].url, "/api/v1/me");
});

test("sends the bearer token of the current session", async () => {
  const fetchMock = mockFetch({ "/dashboard": {} });
  apiModule.setSession("secret-token");

  await api.get("/dashboard");

  const headers = fetchMock.calls[0].init.headers;
  assert.equal(headers.get("Authorization"), "Bearer secret-token");
});

test("raises a typed ApiError for a server error envelope", async () => {
  globalThis.fetch = async () =>
    jsonResponse({ ok: false, err: { code: "offer_disabled", message: "Оффер выключен" } }, 400);

  await assert.rejects(
    () => api.get("/offers/1"),
    (err) => {
      assert.ok(err instanceof apiModule.ApiError, "ошибка — типизированный ApiError");
      assert.equal(err.code, "offer_disabled");
      assert.equal(err.status, 400);
      assert.equal(err.message, "Оффер выключен");
      return true;
    },
  );
});

test("drops the stored session on a 401 response", async () => {
  globalThis.fetch = async () =>
    jsonResponse({ ok: false, err: { code: "unauthorized", message: "нет сессии" } }, 401);
  apiModule.setSession("expired-token");

  await assert.rejects(() => api.get("/me"));
  assert.equal(apiModule.hasSession(), false);
  assert.equal(sessionStorage.getItem("bonvera.session"), null);
});

test("reports a network failure instead of leaking a raw fetch error", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("Failed to fetch");
  };

  await assert.rejects(
    () => api.get("/me"),
    (err) => {
      assert.equal(err.code, "network");
      assert.equal(err.status, 0);
      return true;
    },
  );
});

test("serializes the request body as JSON and sets the content type", async () => {
  const fetchMock = mockFetch({ "/offers/1/take": {} });

  await api.post("/offers/1/take", { age: 21 });

  const init = fetchMock.calls[0].init;
  assert.equal(init.method, "POST");
  assert.equal(init.body, JSON.stringify({ age: 21 }));
  assert.equal(init.headers.get("Content-Type"), "application/json");
});

test("does not force a JSON content type for multipart uploads", async () => {
  const fetchMock = mockFetch({ "/apps/1/proofs": {} });
  const form = new FormData();
  form.append("files", new Blob(["x"]), "proof.png");

  await api.upload("/apps/1/proofs", form);

  assert.equal(fetchMock.calls[0].init.headers.get("Content-Type"), null);
});

test("formats money and dates in the Russian locale", async () => {
  const { rub, fmtDate, fmtDateTime } = await loadModule("/src/lib/format.ts");

  assert.equal(rub(1234), new Intl.NumberFormat("ru-RU").format(1234) + " ₽");
  assert.equal(rub(0), "0 ₽");
  assert.equal(fmtDate(null), "—");
  assert.equal(fmtDateTime(null), "—");
  assert.match(fmtDate("2026-11-14T10:00:00Z"), /2026/);
});
