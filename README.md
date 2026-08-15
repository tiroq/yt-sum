# YT Sum

## Browser extension

`browser-extension/` contains an unpacked Manifest V3 extension. Clicking its toolbar button adds the current standard YouTube video page to the local queue.

1. Start the local API (`./scripts/dev.sh` or `npm run dev:api`).
2. In Chrome or another Chromium browser, open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select `browser-extension`.
3. Open the extension's **Details** page, choose **Extension options**, configure the local address if needed, and save. The default is `http://127.0.0.1:8765`.
4. Open a YouTube video and click the YT Sum Queue button.

For safety the extension can contact only an HTTP service on `localhost` or `127.0.0.1`. Its optional bearer token is sent only to that address and stored in Chrome sync storage; use a trusted browser profile if you choose to set one. Invalid pages, duplicate videos, connection failures, and API errors are shown as notifications.

YT Sum is a local-first macOS library for slow, respectful YouTube transcript collection and structured summarization with Ollama or an OpenAI-compatible endpoint.

## YouTube playlists

Paste a YouTube playlist URL into **Add to library** just like a video URL. YT Sum reads the playlist composition first, records each video's playlist and original position, then appends only videos not already in the library to the processing queue. Re-importing a playlist is safe: it refreshes membership and positions without creating duplicate jobs. Imported playlists appear as their own group in the library; a video's Metadata tab also lists every playlist it belongs to.

The approved product contract is in [docs/SPECIFICATION.md](docs/SPECIFICATION.md). Architecture and portable file formats are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/FILE_FORMAT.md](docs/FILE_FORMAT.md).

## Local development

Requirements: macOS 14.2+, Python 3.11+, Node 22.13+, current yt-dlp, and ffmpeg.

```bash
./scripts/dev.sh
```

The UI opens at `http://127.0.0.1:3000`; the local API listens on `http://127.0.0.1:8765`.

For audio-only fallback, install Meeting Transcriber, enable its Local Automation API, and select WhisperKit or Parakeet in its Transcribe settings. YT Sum reads its owner-only local bearer token and sends only the downloaded local audio path to `127.0.0.1`.

## Updating a Git checkout

The source-update API checks the current Git branch and its upstream. It reports whether the working tree is clean and how many commits are available upstream. This check only refreshes remote references; it never changes source files.

`POST /api/system/source-update/pull` is deliberately enabled only for a clean tree with available upstream commits. The update uses `git pull --ff-only`, so it never creates a merge commit. If local files or commits need attention, the API explains why the update is blocked. After a successful pull, call `POST /api/system/restart`; `scripts/dev.sh` supervises the API and starts it again cleanly.

## Tests

```bash
.venv/bin/python -m pytest
npm test
```

## Release workflow

Release commands are collected in the [Justfile](Justfile). They run local checks, tests, builds, version consistency checks, and release-note drafting; they never publish, deploy, tag, or push.

```bash
just install
just verify
just prepare-release 0.2.0
```

See [docs/RELEASE.md](docs/RELEASE.md) for the full policy, versioning rules, and the manual publication checklist.

## Data ownership

The chosen library folder contains the human-readable transcript, current summary, summary history, cached thumbnail, and `.meta.json` for every video. `.yt-sum/index.sqlite3` is a disposable local index and can be rebuilt from those files.
