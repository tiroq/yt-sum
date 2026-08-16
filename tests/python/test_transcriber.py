import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


@pytest.mark.asyncio
async def test_meeting_transcriber_integration_uses_real_http_calls(tmp_path) -> None:
    token_file = tmp_path / ".rpc-token"
    token_file.write_text("real-token", encoding="utf-8")
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio-data")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            payload = json.dumps({"state": "ready"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            request = json.loads(body.decode("utf-8"))
            self.server.last_request = request
            self.server.last_auth = self.headers.get("Authorization")
            self.server.last_idempotency = self.headers.get("Idempotency-Key")
            payload = json.dumps({"transcript": "[00:00] Speaker: hello\n[00:05] Speaker: there"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = AppSettings(
            meeting_transcriber_url=f"http://127.0.0.1:{server.server_address[1]}",
            meeting_transcriber_token_file=str(token_file),
        )

        bridge = MeetingTranscriberBridge(settings)
        status = await bridge.health()
        segments = await bridge.transcribe(audio_path)

        assert status == {"ready": True, "address": f"http://127.0.0.1:{server.server_address[1]}", "state": "ready", "reason": None}
        assert [segment.text for segment in segments] == ["hello", "there"]
        assert server.last_auth == "Bearer real-token"
        assert server.last_idempotency.startswith("yt-sum-")
        assert server.last_request["path"] == str(audio_path.resolve())
        assert server.last_request["maxWaitSeconds"] == 1800
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
