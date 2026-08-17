# YT Sum

![YT Sum — local-first YouTube transcript and AI summary library](public/images/yt-sum-readme-hero.png)

YT Sum is a local-first macOS app for turning YouTube videos into readable transcripts, summaries, and reusable notes.

It is built for people who want to keep the workflow on their own Mac:

- add one video, many URLs, or a full playlist
- fetch the best available transcript with conservative request pacing
- fall back to audio transcription when subtitles are missing
- summarize with local or OpenAI-compatible models
- store everything in a portable folder of Markdown and JSON files

## Why it exists

YouTube is a good source of information, but long videos are hard to search, compare, and reuse. YT Sum makes them into a local library you can browse, reprocess, and keep under your control.

## What you get

- loopback-only web app and API for macOS
- transcript, summary, thumbnail, metadata, and processing history for each video
- playlist imports without duplicate jobs
- browser extension for one-click queueing from YouTube
- diagnostics for queues, resources, providers, and system state

## Quick start

```bash
./scripts/dev.sh
```

- UI: http://127.0.0.1:3000
- API: http://127.0.0.1:8765

## Requirements

- macOS 14.2+
- Python 3.11+
- Node 22.13+
- `yt-dlp`
- `ffmpeg`
- Optional: Meeting Transcriber for audio-only fallback

## Browser extension

Load `browser-extension/` as an unpacked Manifest V3 extension in Chrome or Chromium.

1. Open `chrome://extensions`
2. Enable Developer mode
3. Choose Load unpacked and select `browser-extension`
4. Set the API address if needed
5. Open a YouTube video and click the queue button

The extension only talks to `localhost` or `127.0.0.1`.

## Data model

Each video lives in its own folder inside the library. The folder contains the transcript, summary, thumbnail, and `.meta.json`. The SQLite database is only a rebuildable index.

## Learn more

- [Product spec](docs/SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [File format](docs/FILE_FORMAT.md)
- [Release process](docs/RELEASE.md)
