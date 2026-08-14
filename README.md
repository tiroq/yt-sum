# YT Sum

YT Sum is a local-first macOS library for slow, respectful YouTube transcript collection and structured summarization with Ollama or an OpenAI-compatible endpoint.

The approved product contract is in [docs/SPECIFICATION.md](docs/SPECIFICATION.md). Architecture and portable file formats are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/FILE_FORMAT.md](docs/FILE_FORMAT.md).

## Local development

Requirements: macOS 14.2+, Python 3.11+, Node 22.13+, current yt-dlp, and ffmpeg.

```bash
./scripts/dev.sh
```

The UI opens at `http://127.0.0.1:3000`; the local API listens on `http://127.0.0.1:8765`.

For audio-only fallback, install Meeting Transcriber, enable its Local Automation API, and select WhisperKit or Parakeet in its Transcribe settings. YT Sum reads its owner-only local bearer token and sends only the downloaded local audio path to `127.0.0.1`.

## Tests

```bash
.venv/bin/python -m pytest
npm test
```

## Data ownership

The chosen library folder contains the human-readable transcript, current summary, summary history, cached thumbnail, and `.meta.json` for every video. `.yt-sum/index.sqlite3` is a disposable local index and can be rebuilt from those files.
