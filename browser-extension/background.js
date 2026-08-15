/* global chrome */
import { DEFAULT_SETTINGS, QueueApiError, enqueueVideo } from "./api-client.js";
const YOUTUBE_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"]);
function isYouTubeVideo(value) {
  try { const url = new URL(value); return YOUTUBE_HOSTS.has(url.hostname) && (url.hostname === "youtu.be" ? url.pathname.length > 1 : url.pathname === "/watch" && Boolean(url.searchParams.get("v"))); }
  catch { return false; }
}
function notify(title, message) { chrome.notifications.create({ type: "basic", iconUrl: "icon.svg", title, message }); }
chrome.runtime.onInstalled.addListener(() => chrome.storage.sync.get(DEFAULT_SETTINGS, (settings) => chrome.storage.sync.set({ ...DEFAULT_SETTINGS, ...settings })));
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.url || !isYouTubeVideo(tab.url)) return notify("YT Sum", "Open a YouTube video first.");
  try {
    const result = await enqueueVideo(tab.url, await chrome.storage.sync.get(DEFAULT_SETTINGS));
    notify("YT Sum", result.existing.length ? "This video is already in your library." : "Video added to the queue.");
  } catch (error) { notify("YT Sum", error instanceof QueueApiError ? error.message : "Unexpected error while adding the video."); }
});
