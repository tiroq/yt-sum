# Pipeline Migration and Recovery

Status: approved on 2026-08-15.

## Legacy import

Existing `jobs` remain available through the compatibility API while the durable workflow schema becomes authoritative.

1. Import completed transcript, summary, prompt, and audio files as verified artifacts.
2. Convert queued legacy jobs to workflows with initial stage tasks.
3. Mark legacy `processing` jobs as interrupted because their former state cannot distinguish waiting from execution.
4. Select the latest verified checkpoint and create only missing descendants.
5. Preserve old logs as legacy history.
6. Do not contact YouTube or a model merely to complete migration.

The migration is idempotent and versioned. It records its completion in SQLite and can be re-run safely after a restored backup.

## Crash recovery

Executors heartbeat leases. On startup, expired attempts become interrupted, live external process ownership is checked, and tasks return to queued only after their checkpoint and temporary output are validated. Temporary output never replaces a final artifact.

Application updates use graceful drain: stop admitting operations, allow short atomic requests to finish within a timeout, interrupt the remainder, persist events, release leases, and restart.

