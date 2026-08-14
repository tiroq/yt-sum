# Local API

Base URL: `http://127.0.0.1:8765/api`. The API is not designed for network exposure.

## Core routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Component and queue status |
| `GET` | `/videos` | Search/filter/sort library |
| `POST` | `/videos` | Normalize URLs and enqueue new videos |
| `GET` | `/videos/{id}` | Metadata, Markdown content, versions |
| `PATCH` | `/videos/{id}` | Favorite and tags |
| `POST` | `/videos/{id}/refresh` | Explicit metadata/transcript refresh |
| `POST` | `/videos/{id}/summaries` | Create a new summary with optional overrides |
| `DELETE` | `/videos/{id}` | Remove index record; optional confirmed folder deletion |
| `GET` | `/jobs` | Queue and recent jobs |
| `POST` | `/jobs/pause` | Pause queue |
| `POST` | `/jobs/resume` | Resume queue |
| `POST` | `/jobs/{id}/retry` | Retry failed/cancelled job |
| `POST` | `/jobs/{id}/cancel` | Cancel queued/current job |
| `POST` | `/jobs/reorder` | Change queued order |
| `GET/PUT` | `/settings` | Read/update non-secret settings |
| `POST` | `/providers/{id}/secret` | Store API key in Keychain |
| `POST` | `/providers/{id}/models` | Test connection and discover models |
| `POST` | `/library/rescan` | Rebuild index from `.meta.json` files |
| `POST` | `/system/yt-dlp/update` | Explicitly update yt-dlp; application restart required |

All errors use `{ "detail": "human-readable message" }`. Job log payloads are redacted before returning.
