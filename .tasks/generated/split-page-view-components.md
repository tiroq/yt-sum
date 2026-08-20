# Task: split page.tsx into separate view files

## Status

planned

## Original Request

Refactor the large frontend page component into separate files for different views so the application is easier to maintain, navigate, and extend.

## Problem Statement

The main page component has grown into a large monolithic file with many responsibilities: library view, settings, status panels, transcript rendering, pipeline views, and helper UI components. This makes the code harder to reason about, review, and change safely.

## Repository Evidence

- The main frontend entry is [app/page.tsx](../../app/page.tsx), and it contains multiple view and helper components in one file.
- The app already has a structured frontend layout split by concerns in the project, and the large page file is a clear outlier.
- The repository instructions prefer small, targeted changes and maintaining a clear separation between product behavior and UI structure.

## Relevant Files

- Frontend: app/page.tsx, app/transcript.ts, app/video-library.js, app/i18n.js
- Backend: backend/ytsum/api.py, backend/ytsum/storage.py
- Tests: tests/rendered-html.test.mjs, tests/video-library.test.mjs
- Config: README.md, docs/ARCHITECTURE.md

## Current Behavior

The app’s main page file contains both view logic and supporting subcomponents in one place, making it harder to maintain and isolate individual view concerns.

## Expected Behavior

- the main page becomes a coordinator or shell component
- individual views and panels are moved into separate files or modules
- code organization reflects the existing app concepts: library, settings, status, transcript, details, and prompts
- behavior remains unchanged from the user’s perspective

## Scope

- refactor large UI component structure into separate files for related views
- extraction of helper subcomponents into dedicated modules
- preservation of the current user-facing behavior and functionality

## Implementation Constraints

- do not change functionality while splitting files
- keep imports and shared types consistent with the existing app structure
- avoid unnecessary broad cleanup outside the page decomposition itself
- maintain compatibility with current client-side rendering and state flow

## Suggested Implementation Approach

1. map the major sections in [app/page.tsx](../../app/page.tsx) into logical groups such as library view, settings, status, transcript, and detail panels
2. extract shared types and small helper functions into a central file or keep them near the relevant feature module
3. create separate files for each major view or group of related UI fragments
4. reduce the main page to orchestration logic and state coordination
5. run the relevant frontend tests to confirm behavior is preserved after the refactor

## Acceptance Criteria

- the large page component is split into separate files for view concerns
- no functional behavior changes are introduced during the refactor
- shared types and helper logic remain consistent and importable
- the codebase is easier to navigate without altering product behavior

## Test Requirements

- run the relevant frontend test suite covering rendered HTML and app behavior
- ensure no UI regressions are introduced by the extraction

## Edge Cases

- circular imports between view modules and shared types
- shared state and callbacks accidentally becoming disconnected after extraction
- helper functions relying on page-local closures being moved incorrectly
- import path drift after the refactor

## Non-Goals

- redesigning the page UI or introducing new features
- changing backend contracts or app data flow
- broad style cleanup outside the file-splitting task

## Open Questions

- should the refactor keep a shared “components” folder for all view fragments, or should each view have its own module?
- is it better to extract by domain (library, settings, status) or by page section (summary, transcript, details)?
- should shared types remain in the main page file or move to a separate type module?
