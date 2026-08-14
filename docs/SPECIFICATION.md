# YT Sum — Product Specification

Status: approved on 2026-08-14. This file is the implementation contract.

## Product goal

YT Sum is a local-first macOS application for collecting YouTube links, obtaining the best available transcript at a deliberately conservative request rate, and producing structured summaries with local or remote language models. The user owns a portable folder of Markdown and JSON files; the database is only a rebuildable index.

## Product boundaries

- Single-user, local application for macOS 14.2 or newer.
- The web interface and API bind to loopback only. There is no account system or LAN access.
- Version 1 accepts individual videos, Shorts, and multiple manually pasted URLs. Playlist/channel expansion is out of scope.
- Public videos are attempted without cookies first. A failed access attempt may retry with an imported `cookies.txt` file or browser cookies.
- The application never downloads the video. Audio is downloaded only when YouTube has no usable transcript.
- The project is delivered as source with a guided local setup; a signed `.app` bundle is a later phase.

## Library and file ownership

- Default library: `~/Documents/YouTube Summaries/`; the user can choose another folder.
- Each video has a readable folder named `YYYY-MM-DD Title [youtube-id]`.
- Every video folder contains `transcript.md`, `summary.md`, `.meta.json`, and a cached thumbnail when available.
- Previous summaries are stored in `summary-history/` and are never silently discarded.
- The application rescans the library at startup and treats `.meta.json` plus Markdown as canonical. SQLite is a disposable search/queue index under `.yt-sum/`.
- Deletion always offers two choices: remove only the index record, or remove the video folder after confirmation.

## Transcript selection tree

1. Author-provided transcript in the primary language.
2. Automatic transcript in the primary language.
3. Author-provided transcript in the secondary language.
4. Automatic transcript in the secondary language.
5. Author or automatic transcript in the video's original language.
6. If no transcript exists, download audio, convert to 16 kHz mono, and transcribe on-device.

Russian and English are the default primary and secondary languages. The chosen transcript is stored by default; other available languages can be fetched manually. Transcript segments preserve timestamps and link back to YouTube. The UI can switch to a clean-text view.

## Safe YouTube access

- One background worker processes one video at a time.
- yt-dlp is configured for long, randomized pauses: 30–90 seconds by default between download steps, with request/subtitle sleeps and exponential retry delays.
- The queue supports pause, resume, cancel, retry, and reordering.
- A terminal failure marks the item as requiring attention and never blocks later jobs.
- Cookies are used only after an unauthenticated attempt fails. Repeated cookie failures are surfaced as an expiry/refresh action.
- Metadata and subtitles refresh only on explicit user action.

## Audio transcription

- Native on-device engines follow the `pasrom/meeting-transcriber` design: WhisperKit as the default 99-language engine and Parakeet TDT v3 as the faster alternative for supported European languages.
- Language detection is automatic. Optional speaker diarization is off by default.
- Model size and download progress must be visible before the user approves a model download.
- The first implementation integrates with Meeting Transcriber's authenticated localhost automation API. The integration is isolated behind a bridge so a bundled Swift companion can replace it without changing the queue or file format.
- Audio is deleted after successful transcription by default; retention is configurable.

## Summarization

- Providers: native Ollama and OpenAI-compatible endpoints (Ollama, LM Studio, vLLM, OpenRouter, and similar).
- Settings include endpoint URL, API key, discovered model list, manual model name, temperature, response limit, chunk size, and per-endpoint requests per minute.
- Remote endpoints default to 10 RPM; local endpoints are unlimited. API keys are stored in the macOS Keychain and never written to Markdown, JSON metadata, or logs.
- Selecting a remote endpoint requires explicit confirmation that transcript text leaves the Mac.
- Default mode covers the entire transcript: chunk summaries are produced first, then reduced to one structured final summary.
- Fast mode follows the referenced tutorial: 2,000-character recursive chunks, BGE embeddings, K-means clusters, representative chunks, then a single summary request. It is explicitly labeled lossy.
- Summary language is independent of transcript language and defaults to Russian.
- Built-in templates include structured notes, concise summary, key ideas, and actions. Users can add/edit templates.
- The default structured output contains a short summary, key ideas, detailed notes, conclusions/actions, and timestamp citations when possible.
- Changing transcript, model, language, or template marks the result stale. Reprocessing is manual and preserves every prior summary.

## Interface

- Responsive Russian/English interface, Russian by default.
- Left rail: search, status/tag/language/favorite filters, sorting, thumbnails, and all added videos.
- Main view: Summary, Transcript, and Metadata/Processing tabs.
- Global queue is always visible and exposes progress plus controls.
- Settings cover languages, library, download pacing, cookies, providers/models, summary templates, transcription, and advanced values.
- System Status reports yt-dlp, ffmpeg, native transcription bridge, cookies, and provider connectivity with actionable guidance.
- Duplicate URLs resolve by YouTube video ID and open the existing item, offering transcript refresh or a new summary.

## Failure, privacy, and observability

- Transcript and summary are separate stages. A summary failure never causes another YouTube request.
- Per-job logs are copyable from the UI, redact credentials, and expire after 30 days.
- Partially completed artifacts are retained when valid.
- The application shows whether a transcript is author-provided, automatic, original-language fallback, or locally transcribed.

## Acceptance criteria

1. A user can paste one or more YouTube URLs and immediately see queued records.
2. Processing survives page reloads and app restarts.
3. Subtitle priority follows the exact selection tree above.
4. A video folder is readable without the application and can rebuild the search index.
5. Ollama/OpenAI-compatible model discovery and manual model entry both work.
6. The configured RPM applies to every summary request, including map and reduce steps.
7. The UI displays partial/failure states without losing completed transcript work.
8. Automated tests cover URL normalization, subtitle selection, caption parsing, file persistence, chunking, and API basics.

