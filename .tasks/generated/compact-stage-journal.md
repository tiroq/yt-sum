# Task: compact stage journal redesign

## Status

planned

## Original Request

Redesign the stage journal to a more compact view so users can scan progress, failures, and milestones with less visual noise.

## Problem Statement

The current stage journal is likely too verbose or dense for fast monitoring during long-running processing. A more compact view would make it easier to understand what happened recently, which step is active, and where a failure occurred without reading a large log-like timeline.

## Repository Evidence

- The project documents a durable pipeline, state transitions, and diagnostics in [docs/PIPELINE.md](../../docs/PIPELINE.md), [docs/PIPELINE_STATE_MACHINE.md](../../docs/PIPELINE_STATE_MACHINE.md), and [docs/DIAGNOSTICS.md](../../docs/DIAGNOSTICS.md).
- The architecture notes the importance of diagnostics and persisted workflow history in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- The backend stores queue and pipeline state in [backend/ytsum/pipeline.py](../../backend/ytsum/pipeline.py) and related modules.
- The app front end has user-facing workflow and status surfaces in [app/](../../app/).

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/pipeline.py, backend/ytsum/api.py, backend/ytsum/storage.py
- Tests: tests/python/test_pipeline.py, tests/python/test_api.py
- Config: docs/DIAGNOSTICS.md, docs/PIPELINE*.md

## Current Behavior

The journal likely exposes a broader or more verbose event stream than necessary, which makes progress tracking harder in longer workflows.

## Expected Behavior

- the stage journal shows a compact, scannable record of recent events
- active, completed, and failed stages are easier to distinguish
- important status changes remain visible without excessive detail
- the compact view still preserves enough information for debugging and diagnostics

## Scope

- redesign of the stage journal presentation
- compact event summarization while keeping important diagnostics
- user-facing clarity for active and failed stages

## Implementation Constraints

- preserve the underlying pipeline/event data model and diagnostics semantics
- do not remove critical failure or state information needed for debugging
- keep the compact view consistent with the local-first architecture and the existing diagnostics contract

## Suggested Implementation Approach

1. inspect the current journal output and the event/state fields that drive it
2. identify the minimal set of fields needed for a compact but useful reading experience
3. redesign the rendering to group or summarize repeated entries and keep key states prominent
4. make sure failures, retries, and stage transitions remain visible in the condensed view
5. validate the design with focused UI and pipeline-related tests or snapshots

## Acceptance Criteria

- the stage journal is more compact and easier to scan
- key transitions and failures remain visible
- the journal still reflects the underlying pipeline state accurately
- no critical diagnostic information is lost in the condensed view

## Test Requirements

- add or update tests covering the rendered compact journal representation
- verify that current pipeline state and failure information still appear correctly
- run the relevant frontend or API tests covering status and diagnostics surfaces

## Edge Cases

- long-running workflows with many repeated state changes
- failure followed by retry or recovery
- large numbers of events in a short time window
- state transitions with minimal human-readable context

## Non-Goals

- redesigning the full diagnostics system beyond the journal presentation
- changing the underlying pipeline state machine contract
- removing historical data or event persistence

## Open Questions

- should the compact view be a summary-only panel, or should it still allow expansion to full journal entries?
- is the redesign intended for the app UI only, or also for exported diagnostics views?
- should the compact journal preserve timestamps, stage names, and error summaries in a single condensed line format?
