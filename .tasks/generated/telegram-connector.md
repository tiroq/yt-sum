# Task: Telegram connector for adding and managing videos

## Status

planned

## Original Request

Add a Telegram connector that can:

- add new videos to the app
- send back processed summaries
- list videos
- archive a video
- delete a video from the app without deleting local data
- restrict bot use to an admin allowlist of authorized Telegram users

## Problem Statement

The app currently focuses on local-first library management and browser-based workflows, but it does not yet provide a Telegram interface for remote tasking and summary delivery. This creates friction for users who want to enqueue videos and receive processed results through Telegram while keeping local artifacts on disk. The bot also needs explicit user authorization so it is only usable by approved admins.

## Repository Evidence

- The app is a local-first YouTube transcript and summary workflow as described in [README.md](../../README.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- The frontend app and local API are separated from the durable library, and the backend owns orchestration and storage logic in [backend/ytsum/](../../backend/ytsum/).
- The local library and metadata model already exist in [backend/ytsum/storage.py](../../backend/ytsum/storage.py) and related modules.
- The project already has a lightweight queue and processing pipeline that can be extended for external commands.

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/api.py, backend/ytsum/storage.py, backend/ytsum/queue.py, backend/ytsum/pipeline.py
- Tests: tests/python/test_api.py, tests/python/test_storage.py, tests/python/test_pipeline.py
- Config: README.md, docs/ARCHITECTURE.md, docs/API.md

## Current Behavior

The app supports local library management and processing workflows, but there is no Telegram bot or messaging-based command layer to trigger those actions remotely.

## Expected Behavior

- a Telegram bot can accept a URL and enqueue a new video for processing
- the bot can send processed summaries back to the user
- the bot can list available videos in the library
- the bot can archive a video without removing local stored data
- the bot can delete a video from the app while leaving local data untouched
- only Telegram users on the configured admin allowlist can interact with the bot
- unauthorized users receive a clear rejection message and no command execution

## Scope

- Telegram bot command layer
- integration with existing queue and library APIs
- summary delivery back to Telegram
- archive/delete flows on app-managed metadata only
- admin allowlist configuration and enforcement

## Implementation Constraints

- keep local-first behavior intact; Telegram should be an interface, not a source of truth
- do not delete local library data when the app-level delete command is used
- preserve existing local API and storage contracts unless updated by design
- ensure the Telegram integration is loopback-safe and does not create remote storage requirements
- admin access must be explicit and enforced before any command executes
- configuration for allowed Telegram user IDs should be stored locally and not exposed as a public remote setting

## Suggested Implementation Approach

1. inspect the current API and storage model for video listing, archive, and deletion operations
2. identify the existing request flow from the app into the library and pipeline
3. add a lightweight Telegram bot service that maps commands to backend operations
4. implement command handlers for add, list, archive, delete, and summary delivery
5. ensure the bot uses existing app state and emits clear user feedback for success and failure cases
6. validate with focused API and integration tests covering command-to-backend behavior

## Acceptance Criteria

- Telegram commands can add a new video for processing
- processed summaries are sent back to Telegram
- a list command returns videos available in the app
- archive and delete commands are both supported with correct semantics
- deleting from the app does not delete the underlying local data on disk
- only approved Telegram user IDs can use the bot
- unauthorized users are rejected with a clear message and no action is taken

## Test Requirements

- add tests for Telegram command mapping to app actions
- verify archive/delete semantics against local library data and app metadata
- add tests that reject unauthorized Telegram users before commands are executed
- run relevant Python API and storage tests for the managing commands

## Edge Cases

- invalid or missing YouTube URL
- video already queued or already processed
- archive/delete request for a non-existent video
- list command when the library is empty
- bot command rate limits or failed backend calls
- user not on the allowlist
- allowlist empty or misconfigured

## Non-Goals

- full Telegram UI redesign
- remote storage or cloud sync for videos
- changing the summary generation engine or transcript pipeline itself

## Open Questions

- should archive mean “hide from app view” or “mark as inactive but keep local file data”? 
- should delete in Telegram only remove the app record while preserving filesystem artifacts?
- do we want commands for summary-only retrieval, or should all results be sent automatically after processing?
- where should the authorized Telegram user IDs be stored: app config, environment file, or local settings?
