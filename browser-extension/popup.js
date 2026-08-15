/* global chrome */
import { DEFAULT_SETTINGS, QueueApiError, enqueueVideo } from "./api-client.js";

const YOUTUBE_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"]);
const addButton = document.querySelector("#add-video");
const videoStatus = document.querySelector("#video-status");
const result = document.querySelector("#result");
let currentUrl = "";

function isYouTubeVideo(value) {
  try { const url = new URL(value); return YOUTUBE_HOSTS.has(url.hostname) && (url.hostname === "youtu.be" ? url.pathname.length > 1 : url.pathname === "/watch" && Boolean(url.searchParams.get("v"))); }
  catch { return false; }
}

async function setBadge(text, color, title) {
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.action.setBadgeText({ text });
  await chrome.action.setTitle({ title });
}

async function initialise() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentUrl = tab?.url || "";
  if (isYouTubeVideo(currentUrl)) {
    videoStatus.textContent = "Current YouTube video is ready.";
    addButton.disabled = false;
  } else {
    videoStatus.textContent = "Open a YouTube video to add it.";
  }
}

addButton.addEventListener("click", async () => {
  addButton.disabled = true;
  result.className = "";
  result.textContent = "Adding video to the queue…";
  await setBadge("…", "#496b91", "YT Sum — Adding video to the queue…");
  try {
    const response = await enqueueVideo(currentUrl, await chrome.storage.sync.get(DEFAULT_SETTINGS));
    const message = response.existing.length ? "This video is already in your library." : "Video added to the queue.";
    result.className = "success";
    result.textContent = message;
    await setBadge("✓", "#237a57", `YT Sum — ${message}`);
  } catch (error) {
    const message = error instanceof QueueApiError ? error.message : "Unexpected error while adding the video.";
    result.className = "error";
    result.textContent = message;
    await setBadge("!", "#b34747", `YT Sum — ${message}`);
    addButton.disabled = false;
  }
});

document.querySelector("#open-settings").addEventListener("click", () => chrome.runtime.openOptionsPage());
document.querySelector("#open-app").addEventListener("click", async () => {
  const settings = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  const appUrl = new URL(settings.serviceUrl);
  appUrl.port = "3000";
  appUrl.pathname = "/";
  appUrl.search = "";
  appUrl.hash = "";
  await chrome.tabs.create({ url: appUrl.toString() });
});

void initialise();
