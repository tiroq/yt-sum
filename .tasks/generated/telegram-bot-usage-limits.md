# Task: Telegram bot usage limits and paid access

## Status

planned

## Original Request

Allow non-admin users to use the Telegram bot under a limited quota and provide a paid package or subscription model for extended access.

## Problem Statement

The Telegram connector will initially be restricted to a trusted admin allowlist, but the product also needs a way for other users to access the bot in a controlled, monetized way. This requires a quota-based access model for non-admin users and a subscription or package-based upgrade path for extra requests.

## Repository Evidence

- The product is a local-first transcript and summary workflow with a multi-surface architecture, as described in [README.md](../../README.md) and [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
- The backend currently owns queueing, processing, and library storage in [backend/ytsum/](../../backend/ytsum/).
- The app’s settings and data model already support local configuration and durable metadata, which can host access control and usage tracking data.
- The Telegram bot task in [telegram-connector.md](telegram-connector.md) defines the bot command layer and admin-authorization requirements.

## Relevant Files

- Frontend: app/
- Backend: backend/ytsum/api.py, backend/ytsum/settings.py, backend/ytsum/storage.py, backend/ytsum/queue.py
- Tests: tests/python/test_api.py, tests/python/test_storage.py, tests/python/test_pipeline.py
- Config: README.md, docs/ARCHITECTURE.md, docs/API.md

## Current Behavior

The bot is currently planned as an admin-only interface. There is no concept of daily request quotas, paid package tiers, or user-level access tracking.

## Expected Behavior

- non-admin users can use the bot within a limited daily quota, such as 1 video per day
- quota usage is tracked and enforced per user
- users can upgrade through a paid package or subscription model for additional access
- admin users retain full unrestricted access
- unauthorized or quota-exhausted users receive clear feedback and no processing occurs

## Scope

- user-level access tracking for the Telegram bot
- quota enforcement for guest or non-admin users
- subscription/package model for extended usage
- integration between pricing model and bot command handlers

## Implementation Constraints

- keep the bot safe and predictable; access should be enforced before any queue action runs
- do not create a remote billing or payment dependency in the initial version unless already part of the product architecture
- maintain local-first data handling and avoid storing sensitive account data in remote systems
- preserve the admin allowlist behavior defined in [telegram-connector.md](telegram-connector.md)

## Suggested Implementation Approach

1. define a user access model with admin, free, and paid tiers
2. decide where quota/account state is stored locally and how it is updated after each bot request
3. add quota enforcement at the bot command boundary before queueing a video or generating a summary
4. define a simple package/subscription mechanism for paid users, with a clear upgrade path and expiry handling
5. add user-facing bot responses for quota remaining, package status, and upgrade instructions
6. validate with focused tests for access, quota exhaustion, and paid-tier behavior

## Acceptance Criteria

- non-admin users can use the bot under a daily or package-limited quota
- a user with exhausted quota cannot enqueue or process additional videos
- paid or subscribed users can exceed the free quota within their purchased allowance
- admin users are unaffected by quota limits
- the package and quota state is persisted and enforced consistently

## Test Requirements

- add tests covering quota enforcement for free users
- add tests confirming paid or subscribed users can exceed the free initial quota
- add tests for admin bypass and quota exhaustion responses
- run the relevant Python API/storage tests for new access-control logic

## Edge Cases

- quota resets across days or subscription expiry
- user buys a package and then exceeds the purchased allowance
- admin user also appears in the free-user list
- invalid or stale subscription state
- user requests the list command when quota is exhausted or expired

## Non-Goals

- building a production payment gateway integration in this task
- redesigning the app’s core pricing model beyond Telegram bot access
- removing the existing admin-only safeguards

## Open Questions

- should the free quota be one video per day per user, or another interval-based limit?
- should paid access be a one-time package or a recurring subscription model?
- is the paid upgrade path only Telegram-based, or should it also be configurable in the app settings UI?
