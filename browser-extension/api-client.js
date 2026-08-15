export const DEFAULT_SETTINGS = Object.freeze({ serviceUrl: "http://127.0.0.1:8765", authorizationToken: "" });

export class QueueApiError extends Error {
  constructor(message, { status, retryable = false } = {}) {
    super(message);
    this.name = "QueueApiError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function serviceEndpoint(serviceUrl) {
  let url;
  try { url = new URL(serviceUrl); } catch { throw new QueueApiError("Service address must be a valid URL."); }
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) {
    throw new QueueApiError("For safety, the service address must use HTTP on localhost or 127.0.0.1.");
  }
  url.pathname = `${url.pathname.replace(/\/$/, "")}/api/videos`;
  url.search = "";
  url.hash = "";
  return url.toString();
}

export async function enqueueVideo(videoUrl, settings, fetchImpl = fetch) {
  const headers = { "Content-Type": "application/json" };
  if (settings.authorizationToken?.trim()) headers.Authorization = `Bearer ${settings.authorizationToken.trim()}`;
  let response;
  try {
    response = await fetchImpl(serviceEndpoint(settings.serviceUrl), { method: "POST", headers, body: JSON.stringify({ urls: [videoUrl] }) });
  } catch (error) {
    if (error instanceof QueueApiError) throw error;
    throw new QueueApiError("Cannot reach YT Sum. Check that the local service is running and the address is correct.", { retryable: true });
  }
  let payload = null;
  try { payload = await response.json(); } catch { /* The API may return a non-JSON error response. */ }
  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? ` ${payload.detail}` : "";
    throw new QueueApiError(`YT Sum rejected the request (${response.status}).${detail}`, { status: response.status, retryable: response.status >= 500 });
  }
  if (!payload || !Array.isArray(payload.jobs) || !Array.isArray(payload.existing) || !Array.isArray(payload.errors)) throw new QueueApiError("YT Sum returned an unexpected response.");
  if (payload.errors.length) throw new QueueApiError(payload.errors[0].error || "YT Sum could not add this URL.");
  return payload;
}
