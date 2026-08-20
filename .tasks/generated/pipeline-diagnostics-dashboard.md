# Task: pipeline diagnostics dashboard

## Status

planned

## Original Request

Create a clearer diagnostics dashboard for pipeline execution so developers can understand task state, resource use, retries, and recovery at a glance.

## Problem Statement

The project already describes a durable pipeline and diagnostics model, but the user-facing experience around active work and failure recovery is not yet surfaced in a way that makes debugging simple. A dedicated diagnostics view would reduce uncertainty during long-running transcript or summary jobs.

## Repository Evidence

- The architecture documents call out the durable pipeline, leases, retries, and diagnostics semantics in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md), [docs/PIPELINE.md](../../docs/PIPELINE.md), [docs/PIPELINE_STATE_MACHINE.md](../../docs/PIPELINE_STATE_MACHINE.md), and [docs/DIAGNOSTICS.md](../../docs/DIAGNOSTICS.md).
- The backend pipeline implementation lives in [backend/ytsum/pipeline.py](../../backend/ytsum/pipeline.py).
- The project already has a diagnostics-focused vocabulary and storage model.

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/pipeline.py, backend/ytsum/api.py, backend/ytsum/queue.py
- Tests: tests/python/test_pipeline.py
- Config: docs/PIPELINE*.md, docs/DIAGNOSTICS.md

## Current Behavior

The system tracks pipeline state and resource events internally, but the information is not yet organized into a developer-friendly dashboard or easy-to-consume API surface.

## Expected Behavior

- developers can inspect tasks by state and resource
- retry, lease, and failure data are visible in a readable format
- active and historical workflow information can be reviewed quickly
- it integrates with the existing local-first diagnostics architecture

## Scope

- diagnostics view for task lifecycle and state transitions
- readable status and error summaries tied to existing pipeline data
- API or UI surface built on persisted pipeline metadata

## Implementation Constraints

- keep pipeline semantics consistent with the state machine definitions
- avoid inventing new lifecycle states outside the documented contract
- preserve loopback-only access and local-first data handling

## Suggested Implementation Approach

1. review the pipeline state machine and diagnostics docs to confirm required state fields
2. inspect the current pipeline API and data returned to the frontend or diagnostics endpoints
3. design a minimal dashboard view grouped by task state, age, resource usage, and retries
4. expose the required metadata through a small backend API surface or existing diagnostics route
5. add tests for state serialization and display-critical edge cases

## Acceptance Criteria

- pipeline tasks can be reviewed by current state and resource
- retry and failure metadata are visible without reading raw logs
- diagnostics output matches the documented state model
- no regression in job execution or recovery behavior

## Test Requirements

- update pipeline and API tests to cover diagnostics output and state visibility
- ensure recovery and retry semantics still pass existing pipeline tests

## Edge Cases

- tasks waiting on a resource lease
- canceled or retried jobs
- stuck tasks with repeated failures
- large queues with many entries and mixed states

## Non-Goals

- reworking the entire orchestration engine
- changing the persistence model beyond the diagnostic data already tracked
- introducing remote telemetry or cloud analytics

## Open Questions

- should the dashboard be a simple status screen, or should it also support task drill-down and history?
- does the UI need a filtered “only active jobs” view, or is a full queue view sufficient?
