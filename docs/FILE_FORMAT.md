# Portable Library Format

## Folder layout

```text
YouTube Summaries/
├── .yt-sum/
│   ├── index.sqlite3
│   └── logs/
└── 2026-08-14 Example title [Gn64NNr3bqU]/
    ├── .meta.json
    ├── thumbnail.jpg
    ├── transcripts/
    │   ├── source/
    │   │   └── original-en-author-20260814T101500Z.vtt
    │   └── original-en-author-20260814T101500Z.md
    ├── summary.md
    ├── artifacts/
    │   └── key-ideas-run-id.md
    └── summary-history/
        └── 20260814T103000Z-llama3.1-structured.md
```

## `.meta.json`

The sidecar is UTF-8, pretty-printed JSON. `schema_version` makes migrations explicit.

```json
{
  "schema_version": 1,
  "video_id": "Gn64NNr3bqU",
  "source_url": "https://www.youtube.com/watch?v=Gn64NNr3bqU",
  "title": "Example title",
  "channel": "Example channel",
  "published_at": "2026-08-14",
  "duration_seconds": 1200,
  "thumbnail_file": "thumbnail.jpg",
  "added_at": "2026-08-14T10:00:00Z",
  "updated_at": "2026-08-14T10:30:00Z",
  "status": "complete",
  "favorite": false,
  "tags": [],
  "transcript": {
    "file": "transcripts/original-en-author-20260814T101500Z.md",
    "raw_file": "transcripts/source/original-en-author-20260814T101500Z.vtt",
    "language": "en",
    "kind": "author",
    "engine": null,
    "segment_count": 240,
    "generated_at": "2026-08-14T10:15:00Z"
  },
  "current_summary": {
    "provider_id": "ollama",
    "model": "llama3.1",
    "template_id": "structured",
    "language": "ru",
    "mode": "complete",
    "generated_at": "2026-08-14T10:30:00Z"
  },
  "summary_versions": []
}
```

Unknown fields must be preserved by future migrations whenever possible. Secrets and cookies are forbidden.

## Transcript artifacts

Files under `transcripts/source/` are byte-preserving downloads and are never
rewritten. Parsing, overlap removal, normalization, and Markdown rendering create
separate derived files under `transcripts/`.

The derived document starts with YAML-compatible front matter, followed by one paragraph per segment. The timestamp itself is a source link.

```markdown
---
video_id: Gn64NNr3bqU
language: en
transcript_kind: author
---

# Example title — Transcript

[00:00](https://www.youtube.com/watch?v=Gn64NNr3bqU&t=0s) Opening sentence.
```

## `summary.md`

The current summary also starts with front matter that records the provider, model, template, language, mode, and generation time. Previous complete files are copied to `summary-history/` before replacement.
