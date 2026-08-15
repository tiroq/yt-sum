from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import TranscriptSegment


TIMESTAMP_RE = re.compile(r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})")
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class SubtitleChoice:
    language: str
    kind: str
    entries: list[dict[str, Any]]


def language_matches(candidate: str, wanted: str) -> bool:
    candidate = candidate.lower().replace("_", "-")
    wanted = wanted.lower().replace("_", "-")
    return candidate == wanted or candidate.startswith(f"{wanted}-")


def matching_key(available: dict[str, Any], wanted: str) -> str | None:
    if wanted in available:
        return wanted
    return next((key for key in available if language_matches(key, wanted)), None)


def select_subtitle(
    subtitles: dict[str, list[dict[str, Any]]],
    automatic: dict[str, list[dict[str, Any]]],
    primary: str,
    secondary: str,
    original_language: str | None,
    allow_any: bool = True,
) -> SubtitleChoice | None:
    for language in (primary, secondary):
        if human_key := matching_key(subtitles, language):
            return SubtitleChoice(human_key, "author", subtitles[human_key])
        if auto_key := matching_key(automatic, language):
            return SubtitleChoice(auto_key, "automatic", automatic[auto_key])

    if original_language:
        if human_key := matching_key(subtitles, original_language):
            return SubtitleChoice(human_key, "original", subtitles[human_key])
        if auto_key := matching_key(automatic, original_language):
            return SubtitleChoice(auto_key, "original", automatic[auto_key])

    if allow_any:
        if subtitles:
            language, entries = next(iter(subtitles.items()))
            return SubtitleChoice(language, "original", entries)
        if automatic:
            language, entries = next(iter(automatic.items()))
            return SubtitleChoice(language, "original", entries)
    return None


def parse_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    seconds = float(parts.pop())
    minutes = int(parts.pop()) if parts else 0
    hours = int(parts.pop()) if parts else 0
    return hours * 3600 + minutes * 60 + seconds


def clean_caption_text(lines: Iterable[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_caption_text(content: str) -> list[TranscriptSegment]:
    lines = content.replace("\r\n", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    index = 0
    last_text = ""
    while index < len(lines):
        match = TIMESTAMP_RE.search(lines[index])
        if not match:
            index += 1
            continue
        text_lines: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index])
            index += 1
        text = clean_caption_text(text_lines)
        if text:
            segments.append(TranscriptSegment(start=parse_timestamp(match.group("start")), end=parse_timestamp(match.group("end")), text=text))
        index += 1
    return merge_rolling_captions(segments)


def parse_caption_file(path: Path) -> list[TranscriptSegment]:
    return parse_caption_text(path.read_text(encoding="utf-8", errors="replace"))


def merge_rolling_captions(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    merged: list[TranscriptSegment] = []
    for segment in segments:
        if merged and segment.text.startswith(merged[-1].text):
            previous = merged[-1]
            merged[-1] = TranscriptSegment(start=previous.start, end=segment.end, text=segment.text, speaker=previous.speaker)
        elif not merged or segment.text != merged[-1].text:
            merged.append(segment)
    return merged


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def transcript_markdown(*, video_id: str, title: str, language: str, kind: str, engine: str | None, segments: list[TranscriptSegment]) -> str:
    frontmatter = ["---", f"video_id: {video_id}", f"language: {language}", f"transcript_kind: {kind}"]
    if engine:
        frontmatter.append(f"engine: {engine}")
    frontmatter.extend(["---", "", f"# {title} — Transcript", ""])
    base_url = f"https://www.youtube.com/watch?v={video_id}"
    body: list[str] = []
    for segment in segments:
        speaker = f"**{segment.speaker}:** " if segment.speaker else ""
        body.append(f"[{format_timestamp(segment.start)}]({base_url}&t={int(segment.start)}s) {speaker}{segment.text}")
    return "\n".join(frontmatter + body).rstrip() + "\n"


def plain_transcript(segments: list[TranscriptSegment]) -> str:
    return "\n".join(segment.text for segment in segments)
