/**
 * Pure display helpers.
 *
 * Kept free of DOM and browser globals so that formatting rules can be
 * unit-tested outside a browser environment (see webapp/tests/).
 */

export function rub(n: number): string {
  return `${Math.round(n).toLocaleString("ru-RU")} ₽`;
}

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
