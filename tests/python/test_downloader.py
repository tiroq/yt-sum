import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yt_dlp

from ytsum.downloader import (
    AppSettings,
    DownloadFailure,
    ExtractedVideo,
    YouTubeClient,
    normalize_playlist_url,
    normalize_youtube_url,
)


@pytest.mark.parametrize(
    "value",
    [
        "Gn64NNr3bqU",
        "https://youtu.be/Gn64NNr3bqU",
        "https://www.youtube.com/watch?v=Gn64NNr3bqU&t=12",
        "https://youtube.com/shorts/Gn64NNr3bqU",
    ],
)
def test_normalize_youtube_url(value: str) -> None:
    video_id, url = normalize_youtube_url(value)
    assert video_id == "Gn64NNr3bqU"
    assert url == "https://www.youtube.com/watch?v=Gn64NNr3bqU"


def test_normalizes_playlist_url() -> None:
    playlist_id, url = normalize_playlist_url("https://youtube.com/watch?v=Gn64NNr3bqU&list=PL12345")
    assert playlist_id == "PL12345"
    assert url == "https://www.youtube.com/playlist?list=PL12345"


def test_rejects_playlist_without_video_when_treated_as_video() -> None:
    with pytest.raises(ValueError):
        normalize_youtube_url("https://youtube.com/playlist?list=abc")


def test_download_audio_with_format_fallback(monkeypatch, tmp_path: Path) -> None:
    """Test that download_audio tries multiple format specs on failure."""
    
    video = ExtractedVideo(
        video_id="test123",
        url="https://www.youtube.com/watch?v=test123",
        title="Test Video",
        channel="Test Channel",
        published_at="2026-01-01",
        duration_seconds=120,
        thumbnail_url=None,
        original_language=None,
        subtitles={},
        automatic_captions={},
    )
    
    download_call_count = 0
    attempted_formats = []
    
    class FallbackYoutubeDL:
        """Mock that fails on first format attempt but succeeds on second."""
        def __init__(self, options):
            nonlocal attempted_formats
            self.options = options
            # Track format attempts during download (skip probing which has no format)
            if options.get("format"):
                attempted_formats.append(options.get("format"))
        
        def __enter__(self):
            return self
        
        def __exit__(self, exc_type, exc, tb):
            return False
        
        def extract_info(self, url, download=False):
            """Mock probing - return fake formats."""
            return {
                "id": "test123",
                "formats": [
                    {"format_id": "140", "acodec": "mp4a", "vcodec": "none"},
                    {"format_id": "251", "acodec": "opus", "vcodec": "none"},
                ]
            }
        
        def download(self, urls):
            nonlocal download_call_count
            download_call_count += 1
            # First format fails, second succeeds
            if download_call_count == 1:
                raise yt_dlp.utils.DownloadError("Requested format is not available")
            # Second format succeeds
            (tmp_path / "source.wav").write_bytes(b"fake audio data")
    
    monkeypatch.setattr("ytsum.downloader.yt_dlp.YoutubeDL", FallbackYoutubeDL)
    monkeypatch.setattr(
        "ytsum.downloader.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""),
    )
    
    client = YouTubeClient(AppSettings())
    result = client.download_audio(video, tmp_path)
    
    # Should have tried at least 2 formats during download
    assert len(attempted_formats) >= 2
    assert attempted_formats[0] == "bestaudio/best"
    assert attempted_formats[1] in ["bestaudio", "best[vcodec^=avc1][acodec^=mp4a]"]
    assert result.name == "audio-16k-mono.wav"


def test_download_audio_all_formats_fail(monkeypatch, tmp_path: Path) -> None:
    """Test that download_audio raises error when all format specs fail."""
    
    video = ExtractedVideo(
        video_id="test123",
        url="https://www.youtube.com/watch?v=test123",
        title="Test Video",
        channel="Test Channel",
        published_at="2026-01-01",
        duration_seconds=120,
        thumbnail_url=None,
        original_language=None,
        subtitles={},
        automatic_captions={},
    )
    
    class FailingYoutubeDL:
        """Mock that always fails."""
        def __init__(self, options):
            pass
        
        def __enter__(self):
            return self
        
        def __exit__(self, exc_type, exc, tb):
            return False
        
        def extract_info(self, url, download=False):
            """Mock probing - return fake formats."""
            return {
                "id": "test123",
                "formats": [
                    {"format_id": "140", "acodec": "mp4a", "vcodec": "none"},
                ]
            }
        
        def download(self, urls):
            raise yt_dlp.utils.DownloadError("Video is not available in your country")
    
    monkeypatch.setattr("ytsum.downloader.yt_dlp.YoutubeDL", FailingYoutubeDL)
    
    client = YouTubeClient(AppSettings())
    with pytest.raises(DownloadFailure) as exc_info:
        client.download_audio(video, tmp_path)
    
    # Should contain the actual error message from the last attempt
    assert "Video is not available in your country" in str(exc_info.value)

