# Task: facts checking prompt

## Status

planned

## Original Request

Add a dedicated facts-checking prompt that can review generated summaries or transcript-derived output and highlight unsupported claims, missing evidence, or likely inaccuracies.

## Problem Statement

The current app focuses on transcript extraction and summarization, but it does not yet provide a formal prompt or workflow for validating factual accuracy against the source transcript. Users need a repeatable, prompt-based fact-checking step to improve trust and reduce unsupported claims.

## Repository Evidence

- The app is a local-first transcript and summary workflow as described in [README.md](../../README.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- The backend summarization pipeline and transcript handling are implemented under [backend/ytsum/](../../backend/ytsum/).
- The frontend is responsible for the user-facing actions and view state in [app/](../../app/).
- The project already stores structured metadata and library items locally, which is a good fit for a prompt-driven verification artifact.

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/summarizer.py, backend/ytsum/api.py, backend/ytsum/storage.py
- Tests: tests/python/test_summarizer.py, tests/python/test_api.py
- Config: README.md, docs/SPECIFICATION.md

## Current Behavior

The system can generate summaries and transcript artifacts, but it does not provide a dedicated prompt-based fact-checking workflow that compares claims to the transcript source.

## Expected Behavior

- users can select or use a facts-checking prompt from the prompt configuration or video view
- the prompt evaluates a summary or artifact against the underlying transcript content
- results flag unsupported claims, weak evidence, or uncertain statements
- the generated fact-check result is stored or surfaced as a local artifact without breaking existing flows

## Scope

- prompt definition for factual verification
- optional UI integration for running the fact-check prompt on a transcript or summary
- result handling and local artifact generation or display

## Implementation Constraints

- keep the fact-check step aligned with local-first behavior and existing transcript/summarization architecture
- do not require a remote service beyond the existing provider model integrations
- keep the solution generic enough to work with the current transcript and summary formats
- maintain compatibility with the current artifact storage model

## Suggested Implementation Approach

1. review current prompt and summarization flows to find the natural integration point
2. identify whether fact-checking should be run against the transcript, summary, or both
3. define a prompt template that reports findings with evidence references back to transcript segments
4. add a settings-level prompt entry and, if needed, a video-view action to trigger generation
5. persist the resulting fact-check artifact and validate the UI and API surfaces with targeted tests

## Acceptance Criteria

- a dedicated facts-checking prompt exists in the prompt system
- the prompt can be run against transcript-based output with evidence-aware review
- the result includes clear findings about unsupported or uncertain claims
- the feature works without breaking existing summary generation flows

## Test Requirements

- add tests covering a facts-check prompt template and its result output format
- validate the API/frontend flow for running a fact-check prompt on a known transcript or summary
- ensure existing summarizer tests still pass

## Edge Cases

- transcript is missing or incomplete
- summary contains high-level claims without exact transcript support
- user runs fact-check on a short or noisy transcript
- multiple source segments support the same claim with conflicting wording

## Non-Goals

- building a full citation model outside the existing app workflow
- rewiring the entire summarization pipeline
- adding remote fact-checking infrastructure or external verification services

## Open Questions

- should fact-check output be a separate artifact or embedded in the summary result panel?
- should the check compare only the summary to transcript, or also review raw extracted notes and metadata?
- do we want a simple pass/fail status, or a richer evidence list with confidence levels?
