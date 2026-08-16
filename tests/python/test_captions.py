from pathlib import Path

from ytsum.captions import parse_caption_file, parse_caption_text, select_original_subtitle, select_subtitle, transcript_markdown


def test_subtitle_priority_prefers_author_primary_then_secondary() -> None:
    choice = select_subtitle(
        subtitles={"en": [{"url": "human-en"}], "ru": [{"url": "human-ru"}]},
        automatic={"ru": [{"url": "auto-ru"}]},
        primary="ru",
        secondary="en",
        original_language="en",
    )
    assert choice is not None
    assert choice.language == "ru"
    assert choice.kind == "author"


def test_subtitle_priority_falls_back_to_automatic_primary() -> None:
    choice = select_subtitle(
        subtitles={"en": [{"url": "human-en"}]},
        automatic={"ru-RU": [{"url": "auto-ru"}]},
        primary="ru",
        secondary="en",
        original_language="en",
    )
    assert choice is not None
    assert choice.language == "ru-RU"
    assert choice.kind == "automatic"


def test_subtitle_priority_uses_original_before_any_language() -> None:
    choice = select_subtitle(
        subtitles={"de": [{"url": "human-de"}], "fr": [{"url": "human-fr"}]},
        automatic={},
        primary="ru",
        secondary="en",
        original_language="fr",
    )
    assert choice is not None
    assert choice.language == "fr"
    assert choice.kind == "original"


def test_original_subtitle_is_selected_independently_of_language_settings() -> None:
    choice = select_original_subtitle(
        subtitles={"en": [{"url": "human-en"}], "ru": [{"url": "human-ru"}]},
        automatic={},
        original_language="en",
    )
    assert choice is not None
    assert (choice.language, choice.kind) == ("en", "original")


def test_original_subtitle_prefers_en_orig_and_ignores_live_chat() -> None:
    choice = select_original_subtitle(
        subtitles={"live_chat": [{"url": "chat"}], "en": [{"url": "human-en"}], "en-orig": [{"url": "human-en-orig"}]},
        automatic={"ru": [{"url": "auto-ru"}]},
        original_language="en",
    )
    assert choice is not None
    assert (choice.language, choice.kind) == ("en-orig", "original")


def test_parse_srt_and_write_clickable_markdown() -> None:
    content = """1
00:00:01,000 --> 00:00:03,200
Hello <b>world</b>

2
00:00:04,000 --> 00:00:06,000
Second line
"""
    segments = parse_caption_text(content)
    assert [segment.text for segment in segments] == ["Hello world", "Second line"]
    markdown = transcript_markdown(video_id="Gn64NNr3bqU", title="Test", language="en", kind="author", engine=None, segments=segments)
    assert "[00:01](https://www.youtube.com/watch?v=Gn64NNr3bqU&t=1s)" in markdown


def test_rolling_caption_fixture_removes_overlaps_without_merging_timings() -> None:
    fixture = Path(__file__).parent / "fixtures" / "rolling-overlap.srt"

    segments = parse_caption_file(fixture)

    assert [(segment.start, segment.end, segment.text) for segment in segments] == [
        (0.0, 2.0, "We are going to talk"),
        (1.5, 3.5, "about caption timing"),
        (3.0, 5.0, "and regression tests"),
    ]
