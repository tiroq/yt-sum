import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function transcriptTools() {
  const source = await readFile(new URL("../app/transcript.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return import(`data:text/javascript,${encodeURIComponent(compiled)}`);
}

const transcript = `---
video_id: abc123
---

# Example — Transcript

[00:03](https://youtube.test/watch?t=3) **Host:** Welcome everyone
[01:12](https://youtube.test/watch?t=72) The second segment
`;

test("parses timestamped transcript lines into independent structured segments", async () => {
  const { parseTranscriptMarkdown } = await transcriptTools();

  assert.deepEqual(parseTranscriptMarkdown(transcript), [
    { timestamp: "00:03", href: "https://youtube.test/watch?t=3", speaker: "Host", text: "Welcome everyone" },
    { timestamp: "01:12", href: "https://youtube.test/watch?t=72", speaker: null, text: "The second segment" },
  ]);
});

test("creates continuous text without timestamps while retaining speaker names", async () => {
  const { parseTranscriptMarkdown, transcriptText } = await transcriptTools();

  assert.equal(transcriptText(parseTranscriptMarkdown(transcript)), "Host: Welcome everyone\nThe second segment");
});

test("transcript view selection is stored and restored by the client", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(page, /localStorage\.getItem\("yt-sum\.transcript\.view"\)/);
  assert.match(page, /localStorage\.setItem\("yt-sum\.transcript\.view", transcriptView\)/);
  assert.match(page, /setView\("structured"\)/);
});
