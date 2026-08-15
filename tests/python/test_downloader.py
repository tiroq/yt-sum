import pytest

from ytsum.downloader import normalize_playlist_url, normalize_youtube_url


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
