from __future__ import annotations

import logging
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import yt_dlp

from .captions import SubtitleChoice, select_original_subtitle, select_subtitle
from .models import AppSettings, PlaylistMeta

logger = logging.getLogger(__name__)


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,200}$")


class DownloadFailure(RuntimeError):
    pass


def normalize_youtube_url(value: str) -> tuple[str, str]:
    value = value.strip()
    if not value:
        raise ValueError("Empty YouTube URL")
    if VIDEO_ID_RE.fullmatch(value):
        return value, f"https://www.youtube.com/watch?v={value}"
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = parsed.path.strip("/").split("/")[1]
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError(f"Unsupported or invalid YouTube URL: {value}")
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def normalize_playlist_url(value: str) -> tuple[str, str]:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    playlist_id = parse_qs(parsed.query).get("list", [""])[0]
    if host not in {"youtube.com", "music.youtube.com"} or not PLAYLIST_ID_RE.fullmatch(playlist_id):
        raise ValueError(f"Unsupported or invalid YouTube playlist URL: {value}")
    return playlist_id, f"https://www.youtube.com/playlist?list={playlist_id}"


def is_playlist_url(value: str) -> bool:
    try:
        normalize_playlist_url(value)
    except ValueError:
        return False
    return True


@dataclass
class ExtractedVideo:
    video_id: str
    url: str
    title: str
    channel: str
    published_at: str | None
    duration_seconds: int | None
    thumbnail_url: str | None
    original_language: str | None
    subtitles: dict
    automatic_captions: dict

    @property
    def available_languages(self) -> list[str]:
        return sorted(set(self.subtitles) | set(self.automatic_captions))


@dataclass
class PlaylistEntry:
    video_id: str
    source_url: str
    position: int


@dataclass
class ExtractedPlaylist:
    meta: PlaylistMeta
    entries: list[PlaylistEntry]


class YouTubeClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def _base_options(self, use_cookies: bool = False) -> dict:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": self.settings.max_download_retries,
            "extractor_retries": self.settings.max_download_retries,
            "sleep_interval_requests": max(1, self.settings.min_download_delay_seconds),
            "sleep_interval_subtitles": self.settings.min_download_delay_seconds,
            "sleep_interval": self.settings.min_download_delay_seconds,
            "max_sleep_interval": self.settings.max_download_delay_seconds,
            "retry_sleep_functions": {
                "http": lambda attempt: min(300, 10 * (2 ** attempt)),
                "extractor": lambda attempt: min(300, 10 * (2 ** attempt)),
            },
            # Handle age-gated and regional content
            "socket_timeout": 60,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
        }
        if use_cookies:
            if self.settings.cookie_file:
                options["cookiefile"] = str(Path(self.settings.cookie_file).expanduser())
            elif self.settings.cookie_browser:
                options["cookiesfrombrowser"] = (self.settings.cookie_browser,)
        return options

    def extract(self, url: str) -> ExtractedVideo:
        info = self._extract_once(url, use_cookies=False)
        if info is None and (self.settings.cookie_file or self.settings.cookie_browser):
            info = self._extract_once(url, use_cookies=True)
        if info is None:
            raise DownloadFailure("yt-dlp could not read this video, with or without configured cookies")
        upload_date = info.get("upload_date")
        published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}" if upload_date and len(upload_date) >= 8 else None
        return ExtractedVideo(
            video_id=info["id"],
            url=info.get("webpage_url") or url,
            title=info.get("title") or f"YouTube video {info['id']}",
            channel=info.get("channel") or info.get("uploader") or "",
            published_at=published_at,
            duration_seconds=int(info["duration"]) if info.get("duration") else None,
            thumbnail_url=info.get("thumbnail"),
            original_language=info.get("language"),
            subtitles=info.get("subtitles") or {},
            automatic_captions=info.get("automatic_captions") or {},
        )

    def extract_playlist(self, url: str) -> ExtractedPlaylist:
        playlist_id, canonical_url = normalize_playlist_url(url)
        options = self._base_options(bool(self.settings.cookie_file or self.settings.cookie_browser))
        options.update({"noplaylist": False, "extract_flat": "discard_in_playlist", "skip_download": True})
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(canonical_url, download=False)
        except yt_dlp.utils.DownloadError as error:
            raise DownloadFailure(str(error)) from error
        if not info:
            raise DownloadFailure("yt-dlp could not read this playlist")
        entries: list[PlaylistEntry] = []
        seen: set[str] = set()
        for position, entry in enumerate(info.get("entries") or [], start=1):
            if not entry:
                continue
            video_id = entry.get("id") or ""
            if not VIDEO_ID_RE.fullmatch(video_id) or video_id in seen:
                continue
            seen.add(video_id)
            entries.append(PlaylistEntry(video_id=video_id, source_url=f"https://www.youtube.com/watch?v={video_id}", position=position))
        return ExtractedPlaylist(
            meta=PlaylistMeta(id=playlist_id, title=info.get("title") or f"YouTube playlist {playlist_id}", source_url=canonical_url, channel=info.get("channel") or info.get("uploader") or "", video_count=len(entries)),
            entries=entries,
        )

    def _extract_once(self, url: str, use_cookies: bool) -> dict | None:
        options = self._base_options(use_cookies)
        options["skip_download"] = True
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                return downloader.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError:
            return None

    def choose_transcript(self, video: ExtractedVideo) -> SubtitleChoice | None:
        return select_subtitle(
            video.subtitles,
            video.automatic_captions,
            self.settings.primary_language,
            self.settings.secondary_language,
            video.original_language,
            self.settings.allow_any_language,
        )

    def choose_original_transcript(self, video: ExtractedVideo) -> SubtitleChoice | None:
        return select_original_subtitle(
            video.subtitles, video.automatic_captions, video.original_language
        )

    def download_subtitle(self, video: ExtractedVideo, choice: SubtitleChoice, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        is_automatic = choice.language not in video.subtitles
        options = self._base_options(False)
        options.update(
            {
                "skip_download": True,
                "writesubtitles": not is_automatic,
                "writeautomaticsub": is_automatic,
                "subtitleslangs": [choice.language],
                "subtitlesformat": "vtt/best",
                "outtmpl": str(work_dir / "subtitle.%(ext)s"),
            }
        )
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([video.url])
        except yt_dlp.utils.DownloadError as error:
            if self.settings.cookie_file or self.settings.cookie_browser:
                options.update(self._base_options(True))
                try:
                    with yt_dlp.YoutubeDL(options) as downloader:
                        downloader.download([video.url])
                except yt_dlp.utils.DownloadError as cookie_error:
                    raise DownloadFailure(str(cookie_error)) from cookie_error
            else:
                raise DownloadFailure(str(error)) from error
        candidates = sorted(work_dir.glob("subtitle*.*"))
        if not candidates:
            raise DownloadFailure(f"yt-dlp reported success but did not save {choice.language} subtitles")
        return candidates[0]

    def download_audio(self, video: ExtractedVideo, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        
        # Use clean YouTube URL format like the debug script
        clean_url = f"https://www.youtube.com/watch?v={video.video_id}"
        logger.info(f"Downloading audio for video {video.video_id}: {clean_url}")
        
        # Try multiple format specs in order of preference, falling back if one fails
        format_specs = [
            "bestaudio/best",  # Best audio stream
            "bestaudio",  # Just audio if available
            "best",  # Any best format
            "bestvideo+bestaudio/best",  # Video + audio combined
            "worstaudio",  # Even the worst audio is better than nothing
        ]
        
        last_error = None
        last_format = None
        
        for format_spec in format_specs:
            last_format = format_spec
            logger.info(f"Trying format: {format_spec}")
            
            try:
                # Match debug script options exactly - minimal configuration
                options = {
                    "format": format_spec,
                    "outtmpl": str(work_dir / "source.%(ext)s"),
                    "quiet": False,
                    "no_warnings": False,
                    "socket_timeout": 60,
                    "http_headers": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    },
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "wav",
                            "preferredquality": "192",
                        }
                    ],
                }
                
                with yt_dlp.YoutubeDL(options) as downloader:
                    downloader.download([clean_url])
                
                # If download succeeded, look for the extracted WAV file
                source = next((path for path in work_dir.glob("source.wav") if path.suffix != ".part"), None)
                if source:
                    logger.info(f"✓ Successfully downloaded audio using format: {format_spec}")
                    wav_path = work_dir / "audio-16k-mono.wav"
                    result = subprocess.run(
                        ["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode != 0:
                        error_msg = result.stderr[-2000:] or "ffmpeg audio conversion failed"
                        logger.error(f"ffmpeg failed: {error_msg}")
                        raise DownloadFailure(error_msg)
                    logger.info(f"✓ Audio converted to 16kHz mono WAV for video {video.video_id}")
                    return wav_path
                else:
                    # Format worked but no WAV produced, try next format
                    logger.warning(f"✗ No WAV file produced with format {format_spec}, trying next")
                    last_error = "yt-dlp did not produce an audio file"
                    # Clean up for next attempt
                    for f in work_dir.glob("source.*"):
                        f.unlink(missing_ok=True)
                    continue
                    
            except yt_dlp.utils.DownloadError as error:
                error_msg = str(error)
                logger.warning(f"✗ Format {format_spec} failed: {error_msg[:200]}")
                last_error = error_msg
                # Clean up for next attempt
                for f in work_dir.glob("source.*"):
                    f.unlink(missing_ok=True)
                continue
            except Exception as error:
                error_msg = str(error)
                logger.warning(f"✗ Unexpected error with format {format_spec}: {error_msg[:200]}")
                last_error = error_msg
                # Clean up for next attempt
                for f in work_dir.glob("source.*"):
                    f.unlink(missing_ok=True)
                continue
        
        # If all formats failed, provide detailed error message
        error_details = f"All {len(format_specs)} format specs failed for video {video.video_id}. Last format: {last_format}, Last error: {last_error[:500]}"
        logger.error(error_details)
        raise DownloadFailure(error_details)

    def cache_thumbnail(self, video: ExtractedVideo, folder: Path) -> Path | None:
        if not video.thumbnail_url:
            return None
        if self.settings.min_download_delay_seconds:
            time.sleep(random.uniform(self.settings.min_download_delay_seconds, self.settings.max_download_delay_seconds))
        try:
            response = httpx.get(video.thumbnail_url, timeout=60, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        suffix = ".webp" if "webp" in response.headers.get("content-type", "") else ".jpg"
        destination = folder / f"thumbnail{suffix}"
        destination.write_bytes(response.content)
        return destination
