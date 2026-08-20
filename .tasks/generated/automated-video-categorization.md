# Task: automated video categorization

## Status

planned

## Original Request

Add automated video categorization so videos can be labeled into categories or tags automatically based on their content, metadata, and transcript.

## Problem Statement

The library is growing and users need a way to organize videos without manual tagging. Without automated classification, discovery and filtering remain limited, and videos are harder to group by topic, interest, or use case.

## Repository Evidence

- The project is a local-first YouTube transcript and summary app as described in [README.md](../../README.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- Library data is stored locally and metadata is tracked in [backend/ytsum/storage.py](../../backend/ytsum/storage.py).
- Transcript and summary processing already happens in [backend/ytsum/captions.py](../../backend/ytsum/captions.py), [backend/ytsum/summarizer.py](../../backend/ytsum/summarizer.py), and related pipeline code.
- The app already has a local library model that can support category metadata without changing the storage contract dramatically.

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/storage.py, backend/ytsum/api.py, backend/ytsum/summarizer.py, backend/ytsum/models.py
- Tests: tests/python/test_storage.py, tests/python/test_summarizer.py, tests/video-library.test.mjs
- Config: README.md, docs/FILE_FORMAT.md, docs/ARCHITECTURE.md

## Current Behavior

Videos are stored and can be listed, but there is no automated category assignment or topic-based grouping built into the pipeline.

## Expected Behavior

- videos are assigned categories or tags based on their transcript, metadata, or summary
- category assignment is repeatable and consistent for the same video content
- users can filter or browse by category in the library
- category assignment does not overwrite user-defined metadata unexpectedly

## Scope

- automated categorization logic
- category/tag persistence in metadata or library indexing
- optional UI surface for viewing categories and filtering by them

## Implementation Constraints

- preserve the local-first architecture and keep the category data consistent with the library structure
- do not require a remote-only classification backend unless already supported by the app
- avoid breaking the existing metadata format or storage semantics without a migration plan
- keep classification optional and non-destructive to custom user metadata

## Suggested Implementation Approach

1. inspect the current library metadata model and how summaries/transcripts are stored
2. identify what metadata is available to classify a video, such as title, transcript, summary, or tags
3. add a categorization step in the processing pipeline or index rebuild path using the available content
4. store the resulting category list in a structured local field that can be read by the UI
5. expose category-based filters or views in the library list and validate with focused tests

## Acceptance Criteria

- a video can be assigned one or more categories automatically
- the classification is based on available transcript, summary, or metadata content
- category values are persisted in a way that remains compatible with the local library model
- users can group or filter videos by category without breaking the existing library flow

## Test Requirements

- add tests for category generation on known sample transcripts or metadata
- add coverage for persistence and retrieval of category metadata
- verify that category assignment does not break existing library or summary flows

## Edge Cases

- videos with short or low-quality transcript content
- titles or metadata with very little useful signal
- multiple possible categories for the same content
- user-edited tags conflicting with automated categories

## Non-Goals

- building a full taxonomy system with manual admin editing in this task
- changing how the app stores raw transcripts or summaries
- adding external classification services without product design approval

## Open Questions

- should categories be single-select or multi-label?
- should categorization happen only after summary generation, or as soon as metadata is available?
- should categories be part of a public library index or stored only as optional metadata?
