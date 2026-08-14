from ytsum.captions import parse_caption_text, select_subtitle, transcript_markdown


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

