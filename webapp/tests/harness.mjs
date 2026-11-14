/**
 * Offline test harness for the BONVERA Mini App frontend.
 *
 * The npm registry is unreachable in this environment, so vitest/jsdom cannot
 * be installed. Instead the harness boots the project's own Vite installation
 * in SSR mode and renders the real components with react-dom/server, then
 * asserts on the produced markup. That keeps the tests running against the
 * actual application code instead of a copy.
 */
import { createServer } from "vite";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const projectRoot = path.resolve(here, "..");

/** Minimal `sessionStorage` stand-in (Node has no DOM storage). */
const storage = new Map();
if (!globalThis.sessionStorage) {
  globalThis.sessionStorage = {
    getItem: (k) => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: (k) => storage.delete(k),
    clear: () => storage.clear(),
    key: (i) => [...storage.keys()][i] ?? null,
    get length() {
      return storage.size;
    },
  };
}

/** Minimal `window` stand-in; the Telegram SDK is read from it. */
if (!globalThis.window) {
  globalThis.window = {
    Telegram: undefined,
    alert: () => {},
    confirm: () => false,
    open: () => {},
    scrollTo: () => {},
  };
}

let serverPromise = null;

export async function vite() {
  if (!serverPromise) {
    serverPromise = createServer({
      root: projectRoot,
      configFile: false,
      logLevel: "error",
      appType: "custom",
      server: { middlewareMode: true, hmr: false, watch: null },
      esbuild: { jsx: "automatic" },
      optimizeDeps: { noDiscovery: true },
    });
  }
  return serverPromise;
}

/** Load a project module (TS/TSX) through Vite's SSR pipeline. */
export async function loadModule(file) {
  const server = await vite();
  return server.ssrLoadModule(file);
}

export async function closeVite() {
  if (serverPromise) {
    const server = await serverPromise;
    await server.close();
    serverPromise = null;
  }
}

/** Build a `Response` double for the fetch mock. */
export function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
}

/** Install a fetch double that answers by URL substring. */
export function mockFetch(routes) {
  const calls = [];
  const fetchMock = async (input, init) => {
    const url = String(input);
    calls.push({ url, init });
    const key = Object.keys(routes).find((k) => url.includes(k));
    if (!key) {
      return jsonResponse({ ok: false, err: { code: "not_found", message: "нет маршрута" } }, 404);
    }
    const value = routes[key];
    const resolved = typeof value === "function" ? await value(url, init) : value;
    return jsonResponse({ ok: true, data: resolved });
  };
  globalThis.fetch = fetchMock;
  fetchMock.calls = calls;
  return fetchMock;
}

/** Render a component (or any element tree) to static markup. */
export async function render(element) {
  const React = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  return renderToStaticMarkup(element);
}

/** Render a page component inside the session provider and a router. */
export async function renderPage(file, { path = "/", wrap } = {}) {
  const React = await import("react");
  const { MemoryRouter } = await import("react-router-dom");
  const mod = await loadModule(file);
  const { SessionProvider } = await loadModule("/src/state/session.tsx");
  const Page = mod.default;
  const tree = React.createElement(
    MemoryRouter,
    { initialEntries: [path] },
    React.createElement(
      SessionProvider,
      null,
      wrap ? wrap(Page) : React.createElement(Page),
    ),
  );
  return render(tree);
}

/**
 * Render a page for an already authorized user.
 *
 * The Telegram handshake cannot run outside Telegram, so the session context
 * is filled directly — the pages themselves are the real ones.
 */
export async function renderPageAsUser(file, { path = "/", user = userStub(), props } = {}) {
  const React = await import("react");
  const { MemoryRouter } = await import("react-router-dom");
  const mod = await loadModule(file);
  const { SessionContext } = await loadModule("/src/state/session.tsx");
  const Page = mod.default;
  const session = {
    user,
    ready: true,
    error: null,
    login: async () => {},
    refresh: async () => {},
    acceptRules: async () => {},
    logout: () => {},
  };
  const tree = React.createElement(
    MemoryRouter,
    { initialEntries: [path] },
    React.createElement(
      SessionContext.Provider,
      { value: session },
      React.createElement(Page, props),
    ),
  );
  return render(tree);
}

/** A catalog offer stub matching the OfferCard contract. */
export function offerStub(overrides = {}) {
  return {
    id: 11,
    code: "tst_card_a",
    name: "Кредитная карта Тест",
    brand: "Тест Банк",
    brand_slug: "test-bank",
    emoji: "💳",
    category: "cards",
    reward: 500,
    condition: "Оформи карту и сделай покупку",
    hold_days: 14,
    purchase_min: 1000,
    age_min: 18,
    age_max: 65,
    image_url: "/assets/offers/cards/tst_card_a.jpg",
    enabled: true,
    has_partner_link: true,
    network_status: "approved",
    available: true,
    unavailable_reason: null,
    ...overrides,
  };
}

/** A user profile stub matching the UserProfile contract. */
export function userStub(overrides = {}) {
  return {
    id: 1,
    username: "tester",
    name: "Тестер",
    accepted: true,
    adult: true,
    age_years: 24,
    balance: 1000,
    banned: false,
    sbp_bank: "Сбер",
    sbp_phone_masked: "+7 900 000-00-00",
    referrer_id: null,
    created: "2026-11-01T10:00:00Z",
    confirmed_orders: 3,
    level: 2,
    ...overrides,
  };
}

/** A dashboard payload stub matching the Dashboard contract. */
export function dashboardStub(overrides = {}) {
  return {
    wallet: {
      available: 0,
      pending_setup: 0,
      review: 0,
      hold: 0,
      reserved: 0,
      paid_total: 0,
      referral_earned: 0,
      min_withdraw: 300,
    },
    confirmed_orders: 0,
    ten_progress: 0,
    tasks_done: 0,
    tasks_total: 4,
    referral: { invited: 0, qualified: 0, earned: 0 },
    ref_link: "https://t.me/bonvera_test_bot?start=ref_1",
    channel_url: null,
    popular_offers: [],
    achievements_preview: [],
    recent_events: [],
    unread_notifications: 0,
    ...overrides,
  };
}

/** An achievement stub matching the Achievement contract. */
export function achievementStub(overrides = {}) {
  return {
    key: "first_order",
    title: "Первое предложение",
    description: "Оформи любое предложение и получи +10 ₽",
    icon: "gift",
    unlocked: false,
    unlocked_at: null,
    ...overrides,
  };
}

/** A notification stub matching the NotificationItem contract. */
export function eventStub(overrides = {}) {
  return {
    id: "deal:1",
    kind: "deal",
    title: "Заявка #1",
    text: "Заявка взята в работу",
    created: "2026-11-10T12:00:00Z",
    app_id: 1,
    ...overrides,
  };
}
