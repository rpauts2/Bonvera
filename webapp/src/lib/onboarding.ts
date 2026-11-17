/**
 * Флаг первого запуска.
 *
 * Онбординг показывается один раз: отметка живёт в localStorage, поэтому
 * переживает перезапуск Mini App, но не синхронизируется между устройствами.
 * Доступ к хранилищу обёрнут в try/catch: в приватном режиме браузера и в
 * Telegram Desktop localStorage может быть недоступен или запрещён.
 */

export const ONBOARDING_KEY = "bonvera_onboarded";

/** Хранилище или null, если его нет (SSR, тесты, запрещённый localStorage). */
function safeStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

/**
 * Проходил ли пользователь онбординг.
 *
 * Если хранилище недоступно, возвращаем true: лучше не показать онбординг,
 * чем зациклить редирект «главная → онбординг → каталог → главная», когда
 * записать флаг физически невозможно.
 */
export function isOnboarded(): boolean {
  const storage = safeStorage();
  if (!storage) return true;
  try {
    return storage.getItem(ONBOARDING_KEY) === "1";
  } catch {
    return true;
  }
}

/** Запоминает, что онбординг пройден (или пропущен). Ошибки записи не критичны. */
export function markOnboarded(): void {
  const storage = safeStorage();
  if (!storage) return;
  try {
    storage.setItem(ONBOARDING_KEY, "1");
  } catch {
    /* хранилище переполнено или запрещено — онбординг просто покажется ещё раз */
  }
}

/** Сбрасывает флаг. Нужен для отладки и повторного прохождения. */
export function resetOnboarding(): void {
  const storage = safeStorage();
  if (!storage) return;
  try {
    storage.removeItem(ONBOARDING_KEY);
  } catch {
    /* no-op */
  }
}
