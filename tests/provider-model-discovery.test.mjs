import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("model discovery handles an unavailable provider without an unhandled rejection", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /async function discover\(provider: Provider\)[\s\S]*?try \{/);
  assert.match(page, /request<\{ items: string\[\] \}>\([\s\S]*?catch \(cause\)/);
  assert.match(page, /window\.alert\([\s\S]*?Check the endpoint URL/);
});
