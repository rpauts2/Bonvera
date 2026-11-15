import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { projectRoot } from "./harness.mjs";

test("RKO is a visible catalog category and does not query the offers API before offers exist", async () => {
  const source = await readFile(path.join(projectRoot, "src/pages/Catalog.tsx"), "utf8");
  assert.match(source, /\{ key: "rko", label: "РКО" \}/);
  assert.match(source, /if \(category === "rko"\) return null;/);
  assert.match(source, /category === "rko" \? \([\s\S]*Расчётный счёт и РКО[\s\S]*Предложения и условия появятся после проверки партнёрских офферов/);
});
