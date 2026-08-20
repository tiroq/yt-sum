# Task: resume summarization from failed step

## Status

planned

## Original Request

Add the ability to resume summarization from a failed step so partial progress is preserved and the workflow can continue without restarting the whole process.

## Problem Statement

The summarization pipeline can fail at one stage of processing, but the system does not yet provide a robust way to resume from the last successfully completed step. This leads to lost progress, repeated work, and frustrating delays when a long transcript or summary pipeline fails mid-run.

## Repository Evidence

- The architecture explicitly documents a durable pipeline with retries, leases, and recovery semantics in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md), [docs/PIPELINE.md](../../docs/PIPELINE.md), [docs/PIPELINE_STATE_MACHINE.md](../../docs/PIPELINE_STATE_MACHINE.md), and [docs/DIAGNOSTICS.md](../../docs/DIAGNOSTICS.md).
- The backend pipeline logic is implemented in [backend/ytsum/pipeline.py](../../backend/ytsum/pipeline.py), and summary work is handled through [backend/ytsum/summarizer.py](../../backend/ytsum/summarizer.py).
- The product already describes a model where durable workflow state and resource tracking are persisted, which is the right foundation for resumed processing.

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/pipeline.py, backend/ytsum/summarizer.py, backend/ytsum/api.py, backend/ytsum/storage.py
- Tests: tests/python/test_pipeline.py, tests/python/test_summarizer.py, tests/python/test_api.py
- Config: docs/PIPELINE*.md, docs/DIAGNOSTICS.md, README.md

## Current Behavior

The system tracks workflow steps and stage state, but it does not yet expose or enforce an explicit resume-from-failed-step path that preserves completed artifacts and continues from the right next stage.

## Expected Behavior

- if a summarization step fails, the workflow keeps the progress already completed
- the user can resume processing from the failed stage rather than restarting from scratch
- the pipeline correctly identifies the next executable stage based on stored progress and artifacts
- a resumed run does not duplicate or corrupt already-saved intermediate results

## Scope

- resume handling for summarization pipeline failures
- persisted state and stage checkpointing
- recovery logic for partial progress in the local-first pipeline model

## Implementation Constraints

- preserve the durable pipeline design and recovery model already documented in the project
- avoid reintroducing duplicate jobs or corrupted intermediate artifacts
- keep compatibility with the existing local-first storage and library semantics
- do not add remote dependency or queue behavior that breaks the current loopback-only model

## Suggested Implementation Approach

1. review the pipeline state machine and current recovery contract to find the correct place to checkpoint stage completion
2. inspect summarization stages and intermediate artifacts to determine which outputs are safe to reuse
3. add resume logic that rebuilds the next stage from the last successful checkpoint instead of re-running the entire pipeline
4. ensure failed and retried stages are clearly identifiable in diagnostics state
5. validate with focused pipeline and summarizer tests for resume and partial-progress behavior

## Acceptance Criteria

- a summarization run can resume from the last successful step after a failure
- completed intermediate artifacts are reused instead of being regenerated unnecessarily
- the workflow state clearly reflects the failed and next executable stage
- restart behavior remains stable for successful runs and recovered runs

## Test Requirements

- add tests for resuming after a failed stage in the summarization pipeline
- validate that already-completed artifacts are not overwritten incorrectly
- run relevant pipeline and summarizer tests covering failure/recovery behavior

## Edge Cases

- failure occurs before any stage has completed
- failure occurs after a large intermediate artifact is already saved
- multiple retries of the same failed step
- cancellation or interruption while a stage is mid-execution
- mismatch between persisted stage state and actual artifact files

## Non-Goals

- redesigning the whole pipeline scheduling model
- introducing a different execution backend or remote orchestration service
- changing transcript extraction or summarization output semantics beyond recovery behavior

## Open Questions

- should resume happen automatically after a failure, or only when the user explicitly triggers it?
- should the resumed run continue from the exact failed stage or the next stage after the last successful checkpoint?
- how should users see “resume available” state in the UI or diagnostics view?
