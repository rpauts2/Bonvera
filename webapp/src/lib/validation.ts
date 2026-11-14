import { rub } from "./format";

export interface WithdrawalInput {
  /** Raw amount as typed by the user (comma or dot accepted). */
  amount: string;
  /** Minimum withdrawal allowed by the backend. */
  min: number;
  /** Balance that can be withdrawn right now. */
  available: number;
  /** Selected receiving bank. */
  bank: string;
  /** Typed SBP phone. */
  phone: string;
  /** The user asked to reuse the stored SBP phone. */
  useSaved: boolean;
  /** A stored SBP phone exists. */
  hasSavedPhone: boolean;
}

export type WithdrawalValidation =
  | { ok: true; amount: number; bank: string; phone: string | null }
  | { ok: false; message: string };

/**
 * Client-side pre-validation of a withdrawal request.
 *
 * The server re-checks every rule (minimum amount, available balance, SBP
 * phone); this only exists to give immediate, human-readable feedback.
 */
export function validateWithdrawal(input: WithdrawalInput): WithdrawalValidation {
  const value = Number(input.amount.replace(",", "."));
  if (!Number.isFinite(value) || value <= 0) {
    return { ok: false, message: "Введи корректную сумму." };
  }
  if (value < input.min) {
    return { ok: false, message: `Минимальная сумма вывода — ${rub(input.min)}.` };
  }
  if (value > input.available) {
    return { ok: false, message: `Доступно только ${rub(input.available)}.` };
  }
  const bank = input.bank.trim();
  if (!bank) {
    return { ok: false, message: "Выбери банк для перевода по СБП." };
  }
  const reuseSaved = input.useSaved && input.hasSavedPhone;
  const phone = input.phone.trim();
  if (!reuseSaved && !phone) {
    return { ok: false, message: "Укажи телефон, привязанный к СБП, или используй сохранённый." };
  }
  return { ok: true, amount: value, bank, phone: reuseSaved ? null : phone };
}
