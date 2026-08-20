# Task: library search and filters

## Status

planned

## Original Request

Add stronger search and filtering for the video library so users can quickly find videos by metadata, title, transcript state, and processing status.

## Problem Statement

The current app stores video metadata and processing state in a local library, but the user experience does not yet provide a good way to search across that library or narrow results by status. This slows down review, reprocessing, and discovery when the library grows.

## Repository Evidence

- The app is structured as a local-first library system with a durable backend and replaceable UI, as described in [README.md](../../README.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- The backend owns storage and metadata synchronization in [backend/ytsum/storage.py](../../backend/ytsum/storage.py).
- The data model and file format are described in [docs/FILE_FORMAT.md](../../docs/FILE_FORMAT.md).
- The app and browser surfaces are intentionally separate from the durable library state.

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/storage.py, backend/ytsum/api.py
- Tests: tests/video-library.test.mjs, tests/python/test_storage.py
- Config: README.md, docs/ARCHITECTURE.md

## Current Behavior

The library can store and expose metadata, but there is no clear end-user workflow for broad search, filtering, or status-driven drill-down across many items.

## Expected Behavior

- users can search by video title and available metadata
- users can filter by completion state, transcript availability, summary status, or folder status
- results update quickly without breaking local-first behavior
- filtering remains consistent with the persisted library data model

## Scope

- search and filtering in the library UI and backend query layer
- metadata fields already available in local storage
- status descriptors for transcript, summary, and processing state

## Implementation Constraints

- preserve local-first architecture and avoid coupling the UI to a remote service
- keep SQLite metadata indexes rebuildable and consistent with the file library
- do not change the durable storage contract without updating tests and docs

## Suggested Implementation Approach

1. inspect the current library data model and API responses in the storage and API layers
2. identify the current metadata fields and search surface already returned to the frontend
3. add a small backend query or filter contract that supports title and status filtering
4. update the UI to expose search input and status filters without changing file format semantics
5. validate with focused tests for library search behavior and storage metadata consistency

## Acceptance Criteria

- users can search across stored library items by key metadata
- users can filter by at least transcript and summary-related states
- search results are stable and deterministic for the same library contents
- no regression in library import or metadata persistence

## Test Requirements

- add or update tests covering public library search/filter APIs and behavior
- run relevant frontend and Python tests for library and storage flows

## Edge Cases

- empty libraries
- videos missing transcript or summary artifacts
- duplicate metadata or stale index rebuild conditions
- long titles and unusual characters in search input

## Non-Goals

- redesigning the entire app UI
- moving data to a remote database
- changing file format semantics without a migration plan

## Open Questions

- should filtering be scoped to the current library folder only or the full local library?
- is there a preferred status vocabulary for transcript and summary states already used elsewhere in the product?
