# Local API

Base URL: `http://127.0.0.1:8765/api`. The API is not designed for network exposure.

## Core routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Components, full pipeline aggregates, resources, and live stage tasks |
| `GET` | `/diagnostics/snapshot` | Versioned live snapshot with workflow and stage details |
| `GET` | `/diagnostics/events` | Monotonic pipeline events after a cursor |
| `GET` | `/diagnostics/stream` | Server-Sent Events stream with sequence IDs |
| `GET` | `/workflows/{id}` | Workflow, stage tasks, attempts, and events |
| `GET` | `/videos` | Search/filter/sort library |
| `POST` | `/videos` | Normalize video/playlist URLs and enqueue new videos |
| `GET` | `/playlists` | Playlist groups, metadata, and video IDs |
| `GET` | `/videos/{id}` | Metadata, Markdown content, versions |
| `PATCH` | `/videos/{id}` | Favorite and tags |
| `POST` | `/videos/{id}/refresh` | Explicit metadata/transcript refresh |
| `POST` | `/videos/{id}/summaries` | Create a new summary with optional overrides |
| `DELETE` | `/videos/{id}` | Remove index record; optional confirmed folder deletion |
| `GET` | `/jobs` | Queue and recent jobs, including separate `download_items` and `llm_items` lane views |
| `DELETE` | `/jobs` | Remove all inactive processing-history records while keeping queued and processing entries |
| `POST` | `/jobs/pause` | Pause queue |
| `POST` | `/jobs/resume` | Resume queue |
| `POST` | `/jobs/stop` | Cancel all queued and currently running jobs |
| `POST` | `/jobs/{id}/retry` | Retry failed/cancelled job |
| `POST` | `/jobs/{id}/cancel` | Cancel queued/current job |
| `POST` | `/jobs/reorder` | Change queued order |
| `GET/PUT` | `/settings` | Read/update non-secret settings |
| `POST` | `/providers/{id}/secret` | Store API key in Keychain |
| `POST` | `/providers/{id}/models` | Test connection and discover models |
| `POST` | `/library/rescan` | Rebuild index from `.meta.json` files |
| `POST` | `/system/yt-dlp/update` | Explicitly update yt-dlp; application restart required |
| `GET` | `/system/source-update` | Inspect Git checkout, working-tree cleanliness, and upstream commits |
| `POST` | `/system/source-update/pull` | Explicit fast-forward source update; blocked for local changes |
| `POST` | `/system/restart` | Controlled API restart when started by `scripts/dev.sh` |

All errors use `{ "detail": "human-readable message" }`. Job log payloads are redacted before returning.

Playlist URLs passed to `POST /videos` are resolved before jobs are created. The canonical playlist URL, its title, and each video's original position are retained in portable video metadata. Re-importing a playlist updates membership without duplicating library videos or queue jobs.

`GET /jobs` includes transparent summary state: `stage`, `requests_planned`,
`requests_completed`, `summary_source`, provider/model fields, and a timestamped
`stage_log`. The plan may grow if map-reduce needs another merge level; completed
requests include a failed attempt so an error remains visible in the journal.

Compatibility jobs additionally expose `workflow_id`, `execution_state`,
`waiting_for`, and `priority`. `processing` remains available for older clients,
but new clients must use `execution_state`: only `running` means real execution;
`waiting_resource` includes a structured reason.

Diagnostics snapshots are not derived from the paginated `/jobs` response.
Every snapshot has a monotonic `cursor`; clients apply only events with a greater
sequence and request another snapshot after a gap or reconnect.
