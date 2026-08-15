import assert from "node:assert/strict";
import test from "node:test";
import { formatDuration } from "../app/duration.js";

test("formatDuration always includes hours, minutes, and seconds", () => {
  assert.equal(formatDuration(4093), "1 ч 08 мин 13 сек");
  assert.equal(formatDuration(67758), "18 ч 49 мин 18 сек");
  assert.equal(formatDuration(61), "0 ч 01 мин 01 сек");
  assert.equal(formatDuration(0), "0 ч 00 мин 00 сек");
});

test("formatDuration rounds down fractional seconds and rejects invalid values", () => {
  assert.equal(formatDuration(3661.9), "1 ч 01 мин 01 сек");
  assert.equal(formatDuration(null), "");
  assert.equal(formatDuration(-1), "");
});
