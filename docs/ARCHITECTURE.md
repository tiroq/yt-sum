# Architecture

## Runtime topology

```text
Browser (127.0.0.1:3000)
       │ JSON/HTTP
       ▼
Python API (127.0.0.1:8765)
       ├── persistent download/transcription queue
       ├── concurrent LLM worker pool
       ├── yt-dlp + ffmpeg
       ├── transcript selector/parser
       ├── summary provider adapters
       ├── SQLite rebuildable index
       ├── Markdown/JSON library
       └── native ASR bridge ──► Meeting Transcriber API (127.0.0.1:9876)
```

The frontend is intentionally replaceable and does not own durable data. The Python service owns orchestration. The library filesystem is authoritative for completed records; SQLite accelerates queries and persists work-in-progress jobs.

## Backend modules

- `api.py`: loopback API, validation, CORS restricted to local development origins, lifecycle.
- `settings.py`: versioned settings, defaults, atomic writes, macOS paths.
- `storage.py`: SQLite schema, portable library folders, metadata synchronization, full-text search.
- `downloader.py`: yt-dlp metadata/subtitle/audio operations and conservative pacing.
- `captions.py`: language selection, SRT/VTT parsing, de-duplication, Markdown rendering.
- `transcriber.py`: Meeting Transcriber automation API adapter and transcript parsing.
- `providers.py`: Ollama/OpenAI-compatible model discovery and chat calls, Keychain access, RPM limiting.
- `summarizer.py`: complete map-reduce pipeline and optional lossy clustering pipeline.
- `queue.py`: durable download/transcription lane plus concurrent LLM lane, retries, cancellation, partial results, logging.

## Job state machine

```text
queued → waiting → metadata → transcript-selection
                                 ├─ subtitle-download → transcript-ready
                                 └─ audio-download → transcribing → transcript-ready
transcript-ready → summarizing → complete
                        └────────→ attention-required
```

Every transition is persisted. Download/transcription jobs are claimed only by the sequential acquisition worker. Summary, prompt, and speech jobs are claimed by the LLM worker pool. The pool size follows enabled model endpoints, while the shared least-loaded provider scheduler distributes concurrent requests across endpoints and each endpoint's RPM limiter remains authoritative. On restart, interrupted jobs return to `queued`; existing transcript files allow the worker to resume at summarization rather than contacting YouTube again.

## Security model

- Both services bind to loopback only.
- Remote-provider secrets are referenced by a Keychain service/account pair; metadata contains only a boolean indicating whether a key exists.
- Cookies are filesystem paths or browser selectors, never copied into the library.
- Logs pass through redaction before persistence.
- Remote-provider use is opt-in per provider.
- Shells are not used for user-controlled arguments; yt-dlp and ffmpeg are invoked as libraries/argument arrays.

## Replaceable native bridge

`NativeTranscriber` consumes an audio path and returns timestamped segments. Its initial adapter uses Meeting Transcriber's stable `/v1/transcribe?include=transcript` API and bearer token. This preserves the agreed WhisperKit/Parakeet/CoreML implementation while keeping engine-specific Swift code outside the Python process. A future bundled helper only needs to implement the same adapter contract.
