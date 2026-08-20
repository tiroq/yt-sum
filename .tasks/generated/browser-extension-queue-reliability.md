# Task: browser extension queue reliability

## Status

planned

## Original Request

Improve queue reliability in the browser extension so that adding videos from YouTube is more robust, less duplicate-prone, and easier to recover when network or local backend issues happen.

## Problem Statement

The browser extension is intended to push videos into the local library pipeline, but queue reliability issues can cause duplicates, missing jobs, or confusing UX when the API is slow or temporarily unavailable. This should be addressed without making the extension more invasive or remote-dependent.

## Repository Evidence

- The browser extension is described in [README.md](../../README.md) and is implemented in [browser-extension/](../../browser-extension/).
- The local API handles queueing and workflow state through [backend/ytsum/api.py](../../backend/ytsum/api.py) and [backend/ytsum/queue.py](../../backend/ytsum/queue.py).
- The architecture emphasizes local-first processing and loopback-only communication.

## Relevant Files

- Frontend: browser-extension/
- Backend: backend/ytsum/api.py, backend/ytsum/queue.py, backend/ytsum/downloader.py
- Tests: tests/extension-api-client.test.mjs, tests/python/test_api.py
- Config: README.md, docs/ARCHITECTURE.md

## Current Behavior

The extension can add a video for processing, but queue reliability and duplicate handling around retries or repeated clicks need improvement to match expected user behavior.

## Expected Behavior

- repeated queue actions do not create unnecessary duplicates
- transient API failures surface clear feedback to the user
- queued items are visible and recoverable in local logs or state views
- the extension remains loopback-only and respects the local-first architecture

## Scope

- extension action reliability and duplicate guarding
- queue request validation and retry semantics on the loopback API
- UX feedback when a request fails or is already queued

## Implementation Constraints

- maintain browser extension compatibility with Manifest V3
- keep communication restricted to localhost/127.0.0.1
- do not change the durable pipeline contract unless required by a validated bug

## Suggested Implementation Approach

1. inspect the queue request flow from the extension into the local backend API
2. identify duplicate and retry paths already used elsewhere in the project
3. add explicit deduplication or idempotency checks at the queue boundary where appropriate
4. surface clear UI feedback for already-queued or failed requests
5. validate with extension and API tests covering the queue path

## Acceptance Criteria

- repeated queue actions do not create duplicate jobs for the same video under normal user behavior
- failed local requests produce user-visible feedback without crashing the extension
- queue entries remain consistent with backend state and metadata
- existing extension API client behavior remains compatible

## Test Requirements

- add tests that cover duplicate queue requests and transient API failure handling
- run relevant extension and backend API tests before marking complete

## Edge Cases

- the user clicks the queue button repeatedly in quick succession
- the API is unavailable during the request
- the same YouTube URL is queued from multiple contexts
- malformed or missing video metadata from the extension request

## Non-Goals

- redesigning the entire browser extension UI
- adding remote backend dependencies
- changing the core transcript or summary algorithms

## Open Questions

- should duplicate detection be based only on the final YouTube URL, or also on canonicalized metadata fields?
- do we want a visible “already queued” state in the extension popup or only silent deduplication?
