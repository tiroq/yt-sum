import pytest

from ytsum.models import AppSettings
from ytsum.transcriber import MeetingTranscriberBridge, parse_native_transcript


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
