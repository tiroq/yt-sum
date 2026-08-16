import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function importTypeScriptModule(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return import(`data:text/javascript,${encodeURIComponent(compiled)}`);
}

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the YT Sum application shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>YT Sum — Local YouTube Intelligence<\/title>/i);
  assert.match(html, /YT Sum/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("starter preview is fully removed from source", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(page, /local intelligence/);
  assert.match(page, /AddDialog/);
  assert.match(page, /SettingsView/);
  assert.match(page, /quick-archive-button/);
  assert.match(page, /archived=true/);
  assert.match(page, /Local Automation API/);
  assert.match(page, /meeting-transcriber#installation/);
  assert.match(page, /void request<Health>\("\/health"\)/);
  assert.match(page, /\/folder\/open/);
  assert.match(page, /Открыть папку артефактов/);
  assert.match(page, /Переобработать/);
  assert.match(page, /onReprocess=\{refreshVideo\}/);
  const refreshVideo = page.match(/async function refreshVideo\(\) \{[\s\S]*?\n {2}\}\n\n {2}async function openArtifactsFolder/);
  assert.ok(refreshVideo);
  assert.doesNotMatch(refreshVideo[0], /setQueueOpen/);
  assert.match(layout, /YT Sum — Local YouTube Intelligence/);
  assert.doesNotMatch(page + layout + packageJson, /codex-preview|_sites-preview|react-loading-skeleton/);
});

test("icon controls use focus-visible tooltips with consequences", async () => {
  const [page, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /function IconButton/);
  assert.match(page, /aria-describedby=\{tooltipId\}/);
  assert.match(page, /Удалить видео\. Затем можно удалить и локальные файлы/);
  assert.match(page, /Архивировать видео\. Оно исчезнет из обычного списка/);
  assert.match(page, /Обновить видео\. Сбор данных будет поставлен в очередь/);
  assert.match(styles, /\.tooltip-wrap:focus-within > \.tooltip/);
});

test("a background settings refresh preserves an unsaved Settings draft", async () => {
  const { shouldApplySettingsRefresh } = await importTypeScriptModule("../app/settings-refresh.ts");

  assert.equal(shouldApplySettingsRefresh(true), false);
  assert.equal(shouldApplySettingsRefresh(false), true);
});

test("provider enabled control is rendered as a switch", async () => {
  const [page, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(page, /function ToggleSwitch/);
  assert.match(page, /role="switch"/);
  assert.match(page, /Использовать endpoint в обработке/);
  assert.match(styles, /\.toggle-switch-track/);
  assert.match(styles, /\.toggle-switch\.on \.toggle-switch-knob/);
});

test("standalone prompts have their own UI flow and artifact endpoint", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /function PromptPanel/);
  assert.match(page, /\/prompts`, \{ method: "POST"/);
  assert.match(page, /Each run is independent/);
  assert.match(page, /prompt_artifacts/);
});

test("selected prompt artifacts can be dismissed from the exact result view", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /onOpen: \(artifact: PromptArtifact \| null\) => void/);
  assert.match(page, /selected\?\.artifact\.id === artifact\.id \? null : artifact/);
  assert.doesNotMatch(page, /secondary-button.*onClick=\{\(\) => onOpen\(null\)\}/s);
});
