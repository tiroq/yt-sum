from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest

from ytsum import git_update, main
from ytsum.context import ApplicationContext
from ytsum.downloader import YouTubeClient, is_playlist_url, normalize_playlist_url, normalize_youtube_url
from ytsum.keychain import KeychainError, delete_secret, get_secret, set_secret
from ytsum.models import AppSettings, ProviderSettings, TranscriptSegment
from ytsum.providers import (
    AsyncCapacityLimiter,
    AsyncRateLimiter,
    AsyncTokenRateLimiter,
    ProviderClient,
    ProviderError,
    estimate_chat_tokens,
)
from ytsum.settings import SettingsRepository
from ytsum.transcriber import MeetingTranscriberBridge, parse_native_transcript


def test_main_run_calls_uvicorn(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_run(app: str, host: str, port: int, reload: bool) -> None:
        called["app"] = app
        called["host"] = host
        called["port"] = port
        called["reload"] = reload

    monkeypatch.setattr(main.uvicorn, "run", fake_run)
    main.run()
    assert called == {"app": "ytsum.api:app", "host": "127.0.0.1", "port": 8765, "reload": False}


def test_keychain_round_trip_and_errors(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_run(command, capture_output, text, check, **kwargs):
        calls.append((command[0], command[1:]))
        if command[1] == "add-generic-password":
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1] == "find-generic-password":
            return subprocess.CompletedProcess(command, 0, stdout="secret-token\n", stderr="")
        if command[1] == "delete-generic-password":
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("ytsum.keychain.subprocess.run", fake_run)
    set_secret("demo", "top-secret")
    assert get_secret("demo") == "secret-token"
    delete_secret("demo")
    assert calls[0][0] == "security"

    def fake_failure(command, capture_output, text, check, **kwargs):
        if command[1] == "add-generic-password":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="pin failed")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="lookup failed")

    monkeypatch.setattr("ytsum.keychain.subprocess.run", fake_failure)
    with pytest.raises(KeychainError, match="pin failed"):
        set_secret("demo", "value")
    assert get_secret("demo") is None
    set_secret("demo", "")


def test_git_update_status_and_pull_paths(monkeypatch) -> None:
    real_git = git_update._git

    def repo_false(*args, **kwargs):
        return subprocess.CompletedProcess(["git", *args], 1, stdout="", stderr="fatal: not a git repo")

    monkeypatch.setattr(git_update, "_git", repo_false)
    assert git_update._repository_ready() == (False, "This installation is not a Git working tree, so source updates are unavailable.")

    def fake_git(*args, **kwargs):
        cmd = list(args)
        if cmd[:2] == ["rev-parse", "--is-inside-work-tree"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="true\n", stderr="")
        if cmd[:2] == ["status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="", stderr="")
        if cmd[:2] == ["branch", "--show-current"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="main\n", stderr="")
        if cmd[:3] == ["rev-parse", "--abbrev-ref", "--symbolic-full-name"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="origin/main\n", stderr="")
        if cmd[:2] == ["fetch", "--quiet"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="", stderr="")
        if cmd[:3] == ["rev-list", "--left-right", "--count"] or cmd[:4] == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="0\t0\n", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(git_update, "_git", fake_git)
    status = git_update.source_update_status()
    assert status["available"] is True
    assert status["upstream"] == "origin/main"
    assert status["diagnostic"] == "The source checkout is up to date."

    def fake_dirty(*args, **kwargs):
        if args[:2] == ("status", "--porcelain=v1"):
            return subprocess.CompletedProcess(["git", *args], 0, stdout=" M file.txt\n", stderr="")
        return fake_git(*args, **kwargs)

    monkeypatch.setattr(git_update, "_git", fake_dirty)
    dirty = git_update.source_update_status()
    assert dirty["clean"] is False
    assert dirty["diagnostic"] == "Local changes detected. Source updates are blocked until the working tree is clean."

    revlist_calls = {"count": 0}

    def fake_pull(*args, **kwargs):
        cmd = list(args)
        if cmd[:2] == ["rev-parse", "--is-inside-work-tree"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="true\n", stderr="")
        if cmd[:2] == ["status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="", stderr="")
        if cmd[:2] == ["branch", "--show-current"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="main\n", stderr="")
        if cmd[:3] == ["rev-parse", "--abbrev-ref", "--symbolic-full-name"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="origin/main\n", stderr="")
        if cmd[:2] == ["fetch", "--quiet"]:
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="", stderr="")
        if cmd[:3] == ["rev-list", "--left-right", "--count"] or cmd[:4] == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]:
            revlist_calls["count"] += 1
            stdout = "0\t1\n" if revlist_calls["count"] == 1 else "0\t0\n"
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout=stdout, stderr="")
        if cmd[0] == "pull":
            return subprocess.CompletedProcess(["git", *cmd], 0, stdout="fast-forward\n", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(git_update, "_git", fake_pull)
    pull = git_update.pull_source_update()
    assert pull["updated"] is True
    assert pull["restart_required"] is True

    monkeypatch.setattr(git_update, "_git", real_git)

    def fake_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=30)

    monkeypatch.setattr(git_update.subprocess, "run", fake_timeout)
    with pytest.raises(git_update.GitUpdateError, match="did not finish in time"):
        git_update._git("status")

    def fake_missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(git_update.subprocess, "run", fake_missing)
    with pytest.raises(git_update.GitUpdateError, match="Git is not installed"):
        git_update._git("status")


def test_settings_repository_and_context_update_paths(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("YTSUM_STATE_DIR", str(state_dir))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))
    repo = SettingsRepository()
    settings = repo.load()
    assert settings.library_dir == str(tmp_path / "library")
    assert settings.templates[0].id == "structured"

    updated = settings.model_copy(update={"summary_template_id": "ideas", "templates": settings.templates + [settings.templates[0]]})
    saved = repo.save(updated)
    assert saved.summary_template_id == "ideas"

    context = ApplicationContext()
    assert context.storage().library_dir == Path(tmp_path / "library").expanduser().resolve()
    next_settings = context.settings_repo.load().model_copy(update={"library_dir": str(tmp_path / "other")})
    context.save_settings(next_settings)
    assert context.storage().library_dir == Path(tmp_path / "other").expanduser().resolve()


def test_downloader_helpers_and_fallback_paths(monkeypatch, tmp_path: Path) -> None:
    assert normalize_youtube_url("Gn64NNr3bqU") == ("Gn64NNr3bqU", "https://www.youtube.com/watch?v=Gn64NNr3bqU")
    assert is_playlist_url("https://youtube.com/playlist?list=PL12345") is True
    assert normalize_playlist_url("youtube.com/playlist?list=PL12345") == ("PL12345", "https://www.youtube.com/playlist?list=PL12345")

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            if "playlist" in url:
                return {"title": "Playlist", "entries": [{"id": "AAAAAAAAAAA"}, {"id": "AAAAAAAAAAA"}, {"id": "BBBBBBBBBBB"}], "channel": "demo"}
            return {"id": "Gn64NNr3bqU", "webpage_url": url, "title": "Example", "channel": "demo", "upload_date": "20260501", "duration": 120, "thumbnail": "https://example.com/thumb.jpg", "subtitles": {"en": {"default": {"ext": "vtt"}}}, "automatic_captions": {}}

        def download(self, urls):
            (tmp_path / "subtitle.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")

    monkeypatch.setattr("ytsum.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)
    client = YouTubeClient(AppSettings())
    playlist = client.extract_playlist("https://youtube.com/playlist?list=PL12345")
    assert playlist.meta.id == "PL12345"
    assert [entry.video_id for entry in playlist.entries] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]
    video = client.extract("https://www.youtube.com/watch?v=Gn64NNr3bqU")
    assert video.video_id == "Gn64NNr3bqU"
    assert client.choose_transcript(video).language == "en"
    assert client.choose_original_transcript(video).language == "en"
    assert client.download_subtitle(video, client.choose_transcript(video), tmp_path).exists()

    def fake_get(url, timeout=None, follow_redirects=True):
        class Response:
            headers = {"content-type": "image/jpeg"}
            content = b"image-bytes"

            def raise_for_status(self):
                return None
        return Response()

    monkeypatch.setattr("ytsum.downloader.httpx.get", fake_get)
    path = client.cache_thumbnail(video, tmp_path)
    assert path is not None and path.read_bytes() == b"image-bytes"

    class AudioYoutubeDL(FakeYoutubeDL):
        def __init__(self, options):
            super().__init__(options)

        def extract_info(self, url, download=False):
            # Support probing for formats
            return {
                "id": "test123",
                "formats": [
                    {"format_id": "140", "acodec": "mp4a", "vcodec": "none"},
                    {"format_id": "251", "acodec": "opus", "vcodec": "none"},
                ]
            }

        def download(self, urls):
            (tmp_path / "source.wav").write_bytes(b"audio")

    monkeypatch.setattr("ytsum.downloader.yt_dlp.YoutubeDL", AudioYoutubeDL)
    monkeypatch.setattr("ytsum.downloader.subprocess.run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""))
    audio = client.download_audio(video, tmp_path)
    assert audio.name == "audio-16k-mono.wav"

    class FailingYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def download(self, urls):
            raise yt_dlp.utils.DownloadError("bad")

    import yt_dlp
    monkeypatch.setattr("ytsum.downloader.yt_dlp.YoutubeDL", FailingYoutubeDL)
    with pytest.raises(Exception):
        client.download_subtitle(video, client.choose_transcript(video), tmp_path)


def test_transcriber_health_and_parse_branches(monkeypatch) -> None:
    assert parse_native_transcript("[00:00] Speaker: hello\n[00:05] Speaker: there")[-1].end >= 5

    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            return FakeResponse(200, {"state": "idle"})

        async def post(self, url, headers=None, json=None):
            return FakeResponse(200, {"transcript": "[00:00] Speaker: hello"})

    monkeypatch.setattr("ytsum.transcriber.httpx.AsyncClient", FakeAsyncClient)
    audio_path = Path("/tmp/audio.wav")
    audio_path.write_bytes(b"fake-audio")
    bridge = MeetingTranscriberBridge(AppSettings(meeting_transcriber_url="http://127.0.0.1:9876", meeting_transcriber_token_file="/tmp/token.txt"))
    Path("/tmp/token.txt").write_text("abc", encoding="utf-8")
    status = asyncio.run(bridge.health())
    assert status["ready"] is True
    segments = asyncio.run(bridge.transcribe(audio_path))
    assert segments[0].text == "hello"

    class MissingTokenClient(FakeAsyncClient):
        async def get(self, url, headers=None):
            raise OSError("down")

    monkeypatch.setattr("ytsum.transcriber.httpx.AsyncClient", MissingTokenClient)
    bridge_bad = MeetingTranscriberBridge(AppSettings(meeting_transcriber_url="http://127.0.0.1:9876", meeting_transcriber_token_file="/tmp/empty-token.txt"))
    Path("/tmp/empty-token.txt").write_text("", encoding="utf-8")
    status_bad = asyncio.run(bridge_bad.health())
    assert status_bad["reason"] == "token_invalid"


def test_provider_limits_and_client_branches(monkeypatch) -> None:
    limiter = AsyncRateLimiter(2, 5, 10)
    limiter._timestamps.extend([0.0, 0.0])
    limiter._next_allowed_at = 100.0
    assert limiter._retry_after_seconds(10.0) > 0

    token_limiter = AsyncTokenRateLimiter(2, 5, 10)
    assert token_limiter.limit_exceeded(3) is True
    assert token_limiter.retry_after_seconds(3) == 0.0
    assert token_limiter.status()["tokens_per_minute"] == 2

    capacity_limiter = AsyncCapacityLimiter(1)
    assert capacity_limiter.available == 1
    asyncio.run(capacity_limiter.acquire())
    capacity_limiter.release()
    assert capacity_limiter.available == 1

    provider = ProviderSettings(id="demo", name="Demo", kind="openai", base_url="https://example.com/v1", model="gpt-4o-mini", enabled=True)
    client = ProviderClient(provider)
    assert client._openai_base_url() == "https://example.com/v1"
    assert estimate_chat_tokens("system", "user", 10) >= 10

    monkeypatch.setattr("ytsum.providers.get_secret", lambda _provider_id: "abc")
    assert client._headers()["Authorization"] == "Bearer abc"
    assert ProviderClient.statuses([provider])[0]["id"] == "demo"
    assert client.availability()["available"] in {True, False}

    class DummyResponse:
        def __init__(self, payload=None, status_code=200, headers=None):
            self._payload = payload or {}
            self.status_code = status_code
            self.headers = headers or {}
            self.text = ""

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise ProviderError(f"status={self.status_code}")

    class DummyAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            return DummyResponse({"data": [{"id": "gpt-4o-mini"}]})

        async def post(self, url, headers=None, json=None):
            return DummyResponse({"choices": [{"message": {"content": "good"}}]})

    monkeypatch.setattr("ytsum.providers.httpx.AsyncClient", DummyAsyncClient)
    assert asyncio.run(client.list_models()) == ["gpt-4o-mini"]
    assert asyncio.run(client.chat(system="sys", user="user")) == "good"

    class FailClient(DummyAsyncClient):
        async def post(self, url, headers=None, json=None):
            request = httpx.Request("POST", url)
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError("offline", request=request, response=response)

    monkeypatch.setattr("ytsum.providers.httpx.AsyncClient", FailClient)
    monkeypatch.setattr(client, "_assert_privacy", lambda: None)
    with pytest.raises(ProviderError, match="Summary request failed"):
        asyncio.run(client.chat(system="sys", user="user"))
