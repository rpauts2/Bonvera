type HapticStyle = "light" | "medium" | "heavy" | "rigid" | "soft";
type NotificationType = "error" | "success" | "warning";

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { user?: { id: number; first_name?: string; username?: string } };
  version: string;
  platform: string;
  colorScheme: "light" | "dark";
  themeParams: Record<string, string>;
  isExpanded: boolean;
  viewportHeight: number;
  viewportStableHeight: number;
  ready: () => void;
  expand: () => void;
  close: () => void;
  setHeaderColor: (color: string) => void;
  setBackgroundColor: (color: string) => void;
  setBottomBarColor?: (color: string) => void;
  disableVerticalSwipe?: () => void;
  requestFullscreen?: () => void;
  isVersionAtLeast: (v: string) => boolean;
  openLink: (url: string, options?: { try_instant_view?: boolean }) => void;
  openTelegramLink: (url: string) => void;
  sendData: (data: string) => void;
  showPopup?: (params: { title?: string; message: string; buttons?: Array<{ id?: string; type?: string; text?: string }> }, cb?: (id: string) => void) => void;
  showAlert: (message: string, cb?: () => void) => void;
  showConfirm: (message: string, cb: (ok: boolean) => void) => void;
  HapticFeedback?: {
    impactOccurred: (style: HapticStyle) => void;
    notificationOccurred: (type: NotificationType) => void;
    selectionChanged: () => void;
  };
  BackButton?: {
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
  MainButton?: {
    setText: (t: string) => void;
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
    setParams: (p: Record<string, unknown>) => void;
  };
  onEvent: (event: string, cb: (...args: never[]) => void) => void;
  offEvent: (event: string, cb: (...args: never[]) => void) => void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export const tg: TelegramWebApp | undefined = window.Telegram?.WebApp;

export const inTelegram = Boolean(tg && tg.initData !== undefined && tg.platform !== "unknown");

export function initTelegram() {
  if (!tg) return;
  tg.ready();
  tg.expand();
  try {
    tg.setHeaderColor("#05070f");
    tg.setBackgroundColor("#05070f");
    tg.setBottomBarColor?.("#05070f");
  } catch {
    // older clients may not support color methods
  }
  if (tg.isVersionAtLeast("8.0")) {
    try {
      tg.requestFullscreen?.();
    } catch {
      // fullscreen is optional
    }
  }
}

export function haptic(style: HapticStyle = "light") {
  tg?.HapticFeedback?.impactOccurred(style);
}

export function hapticNotify(type: NotificationType) {
  tg?.HapticFeedback?.notificationOccurred(type);
}

export function openExternal(url: string) {
  if (!url) return;
  if (tg && url.startsWith("https://t.me/")) tg.openTelegramLink(url);
  else if (tg) tg.openLink(url);
  else window.open(url, "_blank", "noopener");
}

export function rawInitData(): string {
  return tg?.initData ?? "";
}

export function tgUserHint() {
  return tg?.initDataUnsafe?.user;
}

// Native dialogs require Bot API 6.2; on older clients the SDK methods exist
// but silently no-op (never invoking the callback), so fall back to window.
function nativeDialogs(): boolean {
  return Boolean(tg?.isVersionAtLeast("6.2"));
}

export function showAlert(message: string) {
  if (tg?.showAlert && nativeDialogs()) tg.showAlert(message);
  else window.alert(message);
}

export function showConfirm(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (tg?.showConfirm && nativeDialogs()) tg.showConfirm(message, resolve);
    else resolve(window.confirm(message));
  });
}