import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function helpers() {
  const source = await readFile(new URL("../app/clipboard-prefill.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
  return import(`data:text/javascript,${encodeURIComponent(compiled)}`);
}

test("prefills only supported YouTube video links", async () => {
  const { clipboardPrefillResult } = await helpers();
  assert.deepEqual(clipboardPrefillResult("", " https://youtu.be/Gn64NNr3bqU "), { kind: "prefilled", value: "https://youtu.be/Gn64NNr3bqU" });
  assert.deepEqual(clipboardPrefillResult("", "https://youtube.com/playlist?list=abc"), { kind: "ignored" });
});

test("clipboard prefill does not replace text and reports denied permission", async () => {
  const { clipboardPrefillResult } = await helpers();
  assert.deepEqual(clipboardPrefillResult("https://youtu.be/existing123", "https://youtu.be/Gn64NNr3bqU"), { kind: "ignored" });
  assert.deepEqual(clipboardPrefillResult("", "", new DOMException("Denied", "NotAllowedError")), { kind: "permission-denied" });
});
