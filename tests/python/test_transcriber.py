import pytest

from ytsum.models import AppSettings
from ytsum.transcriber import MeetingTranscriberBridge, TranscriptionBridgeError, parse_native_transcript


def test_parse_meeting_transcriber_output() -> None:
    segments = parse_native_transcript("[00:01] Speaker 1: Hello\n[01:03] Speaker 2: Answer")
    assert len(segments) == 2
    assert segments[0].start == 1
    assert segments[0].end == 63
    assert segments[0].speaker == "Speaker 1"
    assert segments[1].text == "Answer"


@pytest.mark.asyncio
async def test_health_explains_when_automation_token_is_missing(tmp_path) -> None:
    bridge = MeetingTranscriberBridge(AppSettings(meeting_transcriber_url="http://127.0.0.1:9876", meeting_transcriber_token_file=str(tmp_path / ".rpc-token")))

    status = await bridge.health()

    assert status == {"ready": False, "address": "http://127.0.0.1:9876", "state": "unavailable", "reason": "token_missing"}


@pytest.mark.asyncio
async def test_transcribe_includes_audio_file_diagnostics_in_error(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / ".rpc-token"
    token_file.write_text("secret-token", encoding="utf-8")
    audio_path = tmp_path / "audio-16k-mono.wav"
    audio_path.write_bytes(b"audio-data")

    class FakeResponse:
        status_code = 200
        text = "native transcription failed"
        headers = {"content-type": "application/json"}

        def json(self):
            return {"state": "error", "error": "ffmpeg failed: Error opening input file ... Operation not permitted"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            assert url.startswith("http://127.0.0.1:9876/v1/transcribe")
            assert headers["Authorization"] == "Bearer secret-token"
            assert json["path"] == str(audio_path.resolve())
            return FakeResponse()

    monkeypatch.setattr("ytsum.transcriber.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    bridge = MeetingTranscriberBridge(AppSettings(meeting_transcriber_url="http://127.0.0.1:9876", meeting_transcriber_token_file=str(token_file)))

    with pytest.raises(TranscriptionBridgeError, match=r"audio_path=.*exists=True.*is_file=True.*size_bytes=10.*resolved=.*parent_exists=True.*parent_is_dir=True"):
        await bridge.transcribe(audio_path)
