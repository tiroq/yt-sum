from pathlib import Path

from ytsum.models import TranscriptInfo, VideoMeta
from ytsum.storage import LibraryStorage, safe_folder_name


def test_safe_folder_name_removes_filesystem_characters() -> None:
    name = safe_folder_name('A/B: "great" video?', "2026-08-14", "Gn64NNr3bqU")
    assert "/" not in name
    assert ":" not in name
    assert name.endswith("[Gn64NNr3bqU]")


def test_library_round_trip_and_rescan(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    meta = VideoMeta(
        video_id="Gn64NNr3bqU",
        source_url="https://www.youtube.com/watch?v=Gn64NNr3bqU",
        title="Local AI summary",
        channel="Example",
        status="complete",
        transcript=TranscriptInfo(language="en", kind="author", segment_count=1),
    )
    folder = storage.create_video_folder(meta)
    (folder / "transcript.md").write_text("# Transcript\n\nUseful local AI text\n", encoding="utf-8")
    (folder / "summary.md").write_text("# Summary\n\nConcise note\n", encoding="utf-8")
    storage.save_meta(meta, folder)

    detail = storage.get_video(meta.video_id)
    assert detail is not None
    assert detail.meta.title == "Local AI summary"
    assert "Useful local AI text" in detail.transcript_markdown
    assert storage.list_videos(query="Useful")[0]["video_id"] == meta.video_id

    second = LibraryStorage(tmp_path)
    assert second.rescan() == 1
    assert second.get_video(meta.video_id) is not None


def test_jobs_are_persistent_and_ordered(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    first = storage.enqueue("Gn64NNr3bqU", "https://youtu.be/Gn64NNr3bqU")
    second = storage.enqueue("dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ")
    assert [job.id for job in storage.list_jobs()[:2]] == [first.id, second.id]
    claimed = storage.next_job()
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == "processing"

