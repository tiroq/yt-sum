# Task: Markdown rendering on the summary tab

## Status

planned

## Original Request

Add support for Markdown rendering on the summary tab so summary content is displayed with formatting, headings, lists, emphasis, and other rich text rather than plain unformatted text.

## Problem Statement

The app already generates summary content that may include Markdown structure, but the summary tab is not rendering it as rich content. Users are seeing raw Markdown source instead of a polished formatted summary, which reduces readability and makes long summaries harder to scan.

## Repository Evidence

- The app is a frontend plus backend architecture described in [README.md](../../README.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- The frontend app shell and view logic live in [app/](../../app/).
- Transcript and summary rendering logic already exists in related frontend utilities and backend caption-generation files, including [backend/ytsum/captions.py](../../backend/ytsum/captions.py).
- The project has tests around rendered HTML and summary-like outputs, indicating that display formatting is already a product concern.

## Relevant Files

- Frontend: app/page.tsx, app/transcript.ts, app/video-library.js, app/i18n.js
- Backend: backend/ytsum/captions.py, backend/ytsum/summarizer.py, backend/ytsum/api.py
- Tests: tests/rendered-html.test.mjs, tests/transcript.test.mjs, tests/python/test_summarizer.py
- Config: README.md, docs/ARCHITECTURE.md

## Current Behavior

Summary content is likely being rendered as plain text or as raw Markdown source, without converting it into styled HTML for the summary tab view.

## Expected Behavior

- the summary tab renders Markdown content with proper headings, lists, emphasis, and block formatting
- the output remains readable for long-form summaries
- any existing transcript or plain-text fallback behavior remains intact when Markdown is absent
- rendering is consistent with the app’s current UI and content structure

## Scope

- Markdown rendering in the summary tab
- formatting of summary content displayed to users
- preserving existing plain text fallback behavior for non-Markdown summaries

## Implementation Constraints

- keep the change limited to the summary display path unless the underlying content contract requires a broader update
- do not break existing rendering tests or app layout conventions
- preserve the local-first app model; this is a presentation-layer feature rather than a storage change

## Suggested Implementation Approach

1. locate the summary tab rendering path in the frontend and identify the exact data source for summary text
2. inspect any existing rendered HTML or Markdown formatting utilities already used elsewhere in the app
3. add a Markdown-to-HTML rendering step for summary content, keeping sanitization and safe output in mind
4. ensure fallback behavior still works for plain text and non-Markdown summaries
5. validate with focused UI tests around rendered HTML and summary display

## Acceptance Criteria

- the summary tab renders Markdown as formatted content instead of raw text
- headings, lists, emphasis, and similar formatting are visible in the UI
- non-Markdown content continues to render correctly
- no regressions in the summary display or related tests

## Test Requirements

- add or update rendered HTML tests for Markdown summary display
- verify plain text and Markdown summary content both render safely and correctly
- run the focused UI tests that cover the summary rendering path

## Edge Cases

- plain text summaries with no Markdown syntax
- markdown-heavy summaries with nested lists and emphasis
- long summaries that overflow the panel layout
- content containing HTML-like or unsafe strings that should be sanitized

## Non-Goals

- redesigning the entire summary UI
- changing the underlying summary generation logic
- implementing a general document editor or rich text authoring tool

## Open Questions

- should summary rendering use a strict Markdown sanitizer, or can it rely on a trusted rendering library?
- do we want only the summary tab to render Markdown, or should the transcript and other views also support it consistently?
- is there an existing preferred Markdown renderer or sanitized HTML utility already used in the app?
