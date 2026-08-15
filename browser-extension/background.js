/* global chrome */
import { DEFAULT_SETTINGS, QueueApiError, enqueueVideo } from "./api-client.js";
const YOUTUBE_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"]);
function isYouTubeVideo(value) {
  try { const url = new URL(value); return YOUTUBE_HOSTS.has(url.hostname) && (url.hostname === "youtu.be" ? url.pathname.length > 1 : url.pathname === "/watch" && Boolean(url.searchParams.get("v"))); }
  catch { return false; }
}
async function notify(title, message) {
  // Chrome Notifications requires a raster icon on some platforms; the
  // extension's SVG may be rejected. The action badge remains the reliable
  // feedback channel, so never leave an unhandled notification rejection.
  try { await chrome.notifications.create({ type: "basic", iconUrl: "icon.svg", title, message }); }
  catch { /* Badge/title already communicate the result. */ }
}
async function feedback(state, message) {
  const badge = state === "working" ? "…" : state === "success" ? "✓" : "!";
  const color = state === "working" ? "#496b91" : state === "success" ? "#237a57" : "#b34747";
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.action.setBadgeText({ text: badge });
  await chrome.action.setTitle({ title: `YT Sum — ${message}` });
  await notify("YT Sum", message);
}
chrome.runtime.onInstalled.addListener(() => chrome.storage.sync.get(DEFAULT_SETTINGS, (settings) => chrome.storage.sync.set({ ...DEFAULT_SETTINGS, ...settings })));
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.url || !isYouTubeVideo(tab.url)) return feedback("error", "Open a YouTube video first.");
  await feedback("working", "Adding this video to the queue…");
  try {
    const result = await enqueueVideo(tab.url, await chrome.storage.sync.get(DEFAULT_SETTINGS));
    await feedback("success", result.existing.length ? "This video is already in your library." : "Video added to the queue.");
  } catch (error) { await feedback("error", error instanceof QueueApiError ? error.message : "Unexpected error while adding the video."); }
});
