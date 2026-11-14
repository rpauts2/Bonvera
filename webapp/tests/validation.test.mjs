import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { closeVite, loadModule } from "./harness.mjs";

let validateWithdrawal;
let rub;

before(async () => {
  ({ validateWithdrawal } = await loadModule("/src/lib/validation.ts"));
  ({ rub } = await loadModule("/src/lib/format.ts"));
});

after(async () => {
  await closeVite();
});

const base = {
  amount: "500",
  min: 300,
  available: 1000,
  bank: "Сбер",
  phone: "",
  useSaved: true,
  hasSavedPhone: true,
};

test("accepts a valid request and returns the normalized payload", () => {
  const result = validateWithdrawal(base);

  assert.equal(result.ok, true);
  assert.equal(result.amount, 500);
  assert.equal(result.bank, "Сбер");
  assert.equal(result.phone, null, "сохранённый телефон не передаётся заново");
});

test("rejects a non-numeric amount", () => {
  const result = validateWithdrawal({ ...base, amount: "abc" });

  assert.equal(result.ok, false);
  assert.equal(result.message, "Введи корректную сумму.");
});

test("rejects a zero or negative amount", () => {
  for (const amount of ["0", "-100"]) {
    const result = validateWithdrawal({ ...base, amount });
    assert.equal(result.ok, false);
    assert.equal(result.message, "Введи корректную сумму.");
  }
});

test("rejects an amount below the minimum", () => {
  const result = validateWithdrawal({ ...base, amount: "100" });

  assert.equal(result.ok, false);
  assert.equal(result.message, `Минимальная сумма вывода — ${rub(300)}.`);
});

test("rejects an amount above the available balance", () => {
  const result = validateWithdrawal({ ...base, amount: "5000" });

  assert.equal(result.ok, false);
  assert.equal(result.message, `Доступно только ${rub(1000)}.`);
});

test("accepts a comma as the decimal separator", () => {
  const result = validateWithdrawal({ ...base, amount: "450,50" });

  assert.equal(result.ok, true);
  assert.equal(result.amount, 450.5);
});

test("requires a receiving bank", () => {
  const result = validateWithdrawal({ ...base, bank: "  " });

  assert.equal(result.ok, false);
  assert.equal(result.message, "Выбери банк для перевода по СБП.");
});

test("requires a phone when no saved one is used", () => {
  const result = validateWithdrawal({ ...base, useSaved: false });

  assert.equal(result.ok, false);
  assert.equal(result.message, "Укажи телефон, привязанный к СБП, или используй сохранённый.");
});

test("requires a phone when there is no saved one at all", () => {
  const result = validateWithdrawal({ ...base, useSaved: true, hasSavedPhone: false });

  assert.equal(result.ok, false);
  assert.equal(result.message, "Укажи телефон, привязанный к СБП, или используй сохранённый.");
});

test("sends the typed phone when the saved one is not used", () => {
  const result = validateWithdrawal({
    ...base,
    useSaved: false,
    phone: " +7 900 123-45-67 ",
  });

  assert.equal(result.ok, true);
  assert.equal(result.phone, "+7 900 123-45-67");
});
