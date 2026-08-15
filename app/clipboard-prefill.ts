const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

/** Returns true only for YouTube video URLs accepted by the local API. */
export function isSupportedYouTubeUrl(value: string): boolean {
  const trimmed = value.trim();
  if (VIDEO_ID.test(trimmed)) return true;

  let url: URL;
  try {
    url = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
  } catch {
    return false;
  }

  const host = url.hostname.toLowerCase().replace(/^(www\.|m\.)/, "");
  let videoId = "";
  if (host === "youtu.be") videoId = url.pathname.split("/").filter(Boolean)[0] ?? "";
  if (host === "youtube.com" || host === "music.youtube.com") {
    if (url.pathname === "/watch") videoId = url.searchParams.get("v") ?? "";
    if (/^\/(shorts|embed|live)\//.test(url.pathname)) videoId = url.pathname.split("/")[2] ?? "";
  }
  return VIDEO_ID.test(videoId);
}

export type ClipboardPrefillResult =
  | { kind: "prefilled"; value: string }
  | { kind: "ignored" }
  | { kind: "permission-denied" }
  | { kind: "unavailable" };

export function clipboardPrefillResult(currentValue: string, clipboardValue: string, failure?: unknown): ClipboardPrefillResult {
  if (currentValue.trim()) return { kind: "ignored" };
  if (failure) return failure instanceof DOMException && failure.name === "NotAllowedError" ? { kind: "permission-denied" } : { kind: "unavailable" };
  const value = clipboardValue.trim();
  return isSupportedYouTubeUrl(value) ? { kind: "prefilled", value } : { kind: "ignored" };
}
