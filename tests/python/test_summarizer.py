from ytsum.summarizer import split_text, strip_frontmatter


def test_split_text_covers_source_and_respects_size() -> None:
    source = "\n\n".join(f"Paragraph {index}: " + "word " * 30 for index in range(20))
    chunks = split_text(source, maximum=420, overlap=0)
    assert len(chunks) > 1
    assert all(len(chunk) <= 420 for chunk in chunks)
    assert "Paragraph 0" in chunks[0]
    assert "Paragraph 19" in chunks[-1]


def test_strip_frontmatter() -> None:
    assert strip_frontmatter("---\nlanguage: en\n---\n\n# Text") == "# Text"

