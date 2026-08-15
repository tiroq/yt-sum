from pathlib import Path

from ytsum.models import AppSettings
from ytsum.tts import MacSayTTS, markdown_to_speech


def test_markdown_to_speech_removes_frontmatter_and_links() -> None:
    source = "---\ntitle: Note\n---\n# Heading\nSee [the source](https://example.com) and **listen**."
    assert markdown_to_speech(source) == "Heading\nSee the source and listen."


def test_macos_tts_reports_missing_system_tools(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ytsum.tts.shutil.which", lambda _: None)
    service = MacSayTTS(AppSettings())
    assert not service.ready()
    try:
        service.synthesize("hello", tmp_path / "speech.m4a")
    except RuntimeError as error:
        assert "Text-to-Speech" in str(error)
    else:
        raise AssertionError("Expected a clear missing-tool error")
