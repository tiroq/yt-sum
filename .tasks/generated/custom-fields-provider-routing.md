# Task: custom fields for provider routing

## Status

planned

## Original Request

Add support for custom fields such as provider routing configuration so users can specify routing preferences, provider selection, or model targeting through metadata or app settings.

## Problem Statement

The app already supports local model discovery and provider configuration, but there is no first-class support for custom per-item or per-task fields that can carry routing metadata such as provider selection or routing hints. This limits flexibility when using providers like OpenRouter that support routing rules and provider-specific preferences.

## Repository Evidence

- The app is built around a local-first library and provider abstraction, as described in [README.md](../../README.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- Provider discovery and request configuration live in [backend/ytsum/providers.py](../../backend/ytsum/providers.py), with settings in [backend/ytsum/settings.py](../../backend/ytsum/settings.py).
- Task and library metadata flows are handled in [backend/ytsum/storage.py](../../backend/ytsum/storage.py) and related models.
- The current project already supports local settings and metadata storage, which is the natural home for custom routing fields.

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/providers.py, backend/ytsum/settings.py, backend/ytsum/storage.py, backend/ytsum/api.py, backend/ytsum/models.py
- Tests: tests/python/test_api.py, tests/python/test_storage.py, tests/provider-model-discovery.test.mjs
- Config: README.md, docs/ARCHITECTURE.md, docs/API.md
- https://openrouter.ai/docs/guides/routing/provider-selection description of fields

## Current Behavior

The app supports provider configuration at a general level, but it does not have a structured way to store and use custom per-item or per-task metadata such as provider routing preferences.

## Expected Behavior

- users can define custom fields for routing or provider selection
- routing metadata is attached to a task, item, or saved setting in a consistent way
- provider requests can honor custom routing preferences when the provider supports them
- the feature works without breaking existing provider discovery or default behavior

## Scope

- custom field definitions for provider routing metadata
- persistence and retrieval of routing data
- application of routing hints to provider requests where supported
- user-facing settings or metadata editing for these custom fields

## Implementation Constraints

- preserve local-first architecture and avoid making provider routing a remote-only feature
- keep the feature compatible with current provider abstractions and settings storage patterns
- do not silently break existing provider flows when custom fields are absent
- maintain explicit support for providers that accept routing metadata, such as OpenRouter-style provider selection

## Suggested Implementation Approach

1. inspect the provider configuration and request-building path to find where provider-specific options are assembled
2. define a lightweight custom-field schema that can carry routing metadata without changing the whole model unnecessarily
3. add storage and retrieval for this schema in the local settings or item metadata layer
4. update provider request generation to include routing preferences when present and supported
5. validate with targeted tests around storage, settings, and provider request assembly

## Acceptance Criteria

- custom fields can be stored and retrieved for routing-related metadata
- provider requests may include routing preferences when configured
- default behavior remains unchanged when no custom routing field is provided
- the feature remains compatible with the app’s local-first persisted metadata model

## Test Requirements

- add tests covering custom field storage and retrieval
- add tests confirming provider request assembly honors routing metadata when present
- verify default provider behavior remains unchanged when no custom field is set

## Edge Cases

- no custom routing fields configured
- malformed provider routing values
- unsupported provider does not accept routing metadata
- mixed settings across multiple tasks or videos
- multiple custom fields alongside existing metadata

## Non-Goals

- full provider marketplace or remote routing management
- a complete generic metadata schema redesign for unrelated features
- adding vendor-specific logic for all providers in one task

## Open Questions

- should custom routing fields live in global settings, per-video metadata, or per-task payloads?
- do we want a generic “custom_fields” pattern or a more explicit “provider_routing” schema?
- should provider routing only support OpenRouter-style provider selection, or should the model allow future routing keys generically?
