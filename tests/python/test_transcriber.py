from ytsum.transcriber import parse_native_transcript


def test_parse_meeting_transcriber_output() -> None:
    segments = parse_native_transcript("[00:01] Speaker 1: Hello\n[01:03] Speaker 2: Answer")
    assert len(segments) == 2
    assert segments[0].start == 1
    assert segments[0].end == 63
    assert segments[0].speaker == "Speaker 1"
    assert segments[1].text == "Answer"
