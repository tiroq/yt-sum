# Task: redesign prompts tabs

## Status

planned

## Original Request

Add a redesigned prompts workflow with two main areas:

1. In settings, allow creating, editing, and deleting custom prompts.
2. In the video view, let the user select a required prompt from dropdowns and generate artifacts using that prompt from the video page, including a run action there.

## Problem Statement

The current product does not provide a clear, editable prompt management flow. Prompt choices are not easily configurable in settings, and the video view does not let a user pick a prompt and trigger artifact generation directly from the item. This creates friction for users who need per-video prompt selection and repeated prompt customization.

## Repository Evidence

- The app is a local-first transcript and summarization product with a Next.js UI and FastAPI backend, as described in [README.md](../../README.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- The frontend contains the main app shell and video views in [app/](../../app/).
- The backend owns transcript, summary, and artifacts flow in [backend/ytsum/](../../backend/ytsum/).
- The repository has a local-first storage model and settings layer in [backend/ytsum/settings.py](../../backend/ytsum/settings.py) and [backend/ytsum/storage.py](../../backend/ytsum/storage.py).

## Relevant Files

- Frontend: app/page.tsx, app/transcript.ts, app/settings-refresh.ts, app/video-library.js, app/chatgpt-auth.ts
- Backend: backend/ytsum/settings.py, backend/ytsum/api.py, backend/ytsum/summarizer.py, backend/ytsum/models.py
- Tests: tests/*.test.mjs, tests/python/test_api.py, tests/python/test_summarizer.py
- Config: README.md, docs/SPECIFICATION.md, docs/ARCHITECTURE.md

## Current Behavior

Prompt handling is not yet structured as a user-editable settings feature, and the video UI does not expose a prompt selection and execution flow for artifacts generation.

## Expected Behavior

- users can view, add, edit, and delete prompts from the settings area
- prompts are saved in a way that matches the app’s local-first persistence model
- the video view exposes prompt dropdowns for required prompt selection
- artifact generation is triggered from the video page using the selected prompt
- user-visible prompt choices remain consistent with saved configuration

## Scope

- settings-based prompt CRUD flow
- prompt selection dropdowns in the video view
- artifact generation and run action from the video page
- persistence and retrieval of prompt definitions in the local app configuration

## Implementation Constraints

- keep all prompt data local-first and consistent with the project’s settings storage model
- do not add remote dependencies or cloud prompt storage
- preserve current behavior for existing transcript and summary flows unless explicitly changed by this task
- follow existing frontend/backend separation and keep API validation consistent with the service layer

## Suggested Implementation Approach

1. inspect the current settings and app state model to find the right persistence location for prompt configuration
2. inspect how the video view currently renders actions and artifact-generation flows
3. add a backend or settings-layer API for prompt CRUD operations, reusing existing local config patterns
4. update the settings UI to support viewing, creating, editing, and deleting prompts
5. update the video detail page to include dropdown-based prompt selection and a run trigger for artifact generation
6. validate with focused tests around settings persistence and the video-page prompt selection flow

## Acceptance Criteria

- users can create, edit, and delete prompts from settings
- prompt definitions are stored and retrieved correctly using the local app settings model
- video view includes dropdowns for selecting required prompts
- artifact generation can be triggered from the video page using the chosen prompt
- no existing workflow is broken for users who do not use custom prompts

## Test Requirements

- add or update tests for prompt CRUD and video-view prompt selection behavior
- verify settings persistence and API contract behavior around prompt operations
- run the relevant frontend and Python tests covering settings and video flows

## Edge Cases

- empty prompt list
- invalid prompt name or blank content
- deleting a prompt currently selected in a video
- switching between multiple prompts on the same video
- prompt definitions with special characters or long text

## Non-Goals

- redesigning the entire settings UI beyond prompt management
- changing the transcript or summary engine itself
- adding a global prompt marketplace or remote sync feature

## Open Questions

- should each prompt be global across the app, or scoped to a specific library item or user?
- should “required prompt” mean one selected prompt per artifact type or a general prompt selector per action?
- do the generated artifacts need a separate output naming convention, or can they reuse the current artifact flow?
