import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

test("add-video dialog keeps keyboard focus on its link field", () => {
  assert.match(page, /document\.getElementById\("youtube-links"\)[\s\S]*?linksField\?\.focus\(\)/);
  assert.match(page, /event\.key === "Escape"[\s\S]*?onClose\(\)/);
  assert.match(page, /event\.key !== "Tab"[\s\S]*?last\.focus\(\)/);
});

test("add-video dialog returns focus to its opener so it can be opened again", () => {
  assert.match(page, /addDialogTriggerRef\.current = event\.currentTarget/);
  assert.match(page, /addDialogTriggerRef\.current\?\.focus\(\)/);
  assert.match(page, /onClick=\{openAddDialog\}/);
});
