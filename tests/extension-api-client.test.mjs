import assert from "node:assert/strict";
import test from "node:test";
import { QueueApiError, enqueueVideo, serviceEndpoint } from "../browser-extension/api-client.js";
test("builds a local queue endpoint", () => {
  assert.equal(serviceEndpoint("http://127.0.0.1:8765/"), "http://127.0.0.1:8765/api/videos");
  assert.throws(() => serviceEndpoint("https://example.com"), QueueApiError);
});
test("sends the video URL with optional bearer authentication", async () => {
  let received;
  const fetchStub = async (url, options) => { received = { url, options }; return new Response(JSON.stringify({ jobs: [{ id: "job-1" }], existing: [], errors: [] }), { status: 202 }); };
  const result = await enqueueVideo("https://www.youtube.com/watch?v=Gn64NNr3bqU", { serviceUrl: "http://127.0.0.1:8765", authorizationToken: "secret" }, fetchStub);
  assert.equal(result.jobs[0].id, "job-1"); assert.equal(received.url, "http://127.0.0.1:8765/api/videos"); assert.equal(received.options.headers.Authorization, "Bearer secret"); assert.deepEqual(JSON.parse(received.options.body), { urls: ["https://www.youtube.com/watch?v=Gn64NNr3bqU"] });
});
test("returns a retryable safe error when the service is unreachable", async () => {
  await assert.rejects(() => enqueueVideo("https://youtu.be/Gn64NNr3bqU", { serviceUrl: "http://127.0.0.1:8765" }, async () => { throw new TypeError("offline"); }), (error) => error instanceof QueueApiError && error.retryable);
});
