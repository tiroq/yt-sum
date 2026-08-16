from pathlib import Path

from ytsum.models import JobStageEvent, PlaylistMeta, PromptArtifact, TranscriptInfo, VideoMeta
from ytsum.queue import ProcessingQueue
from ytsum.storage import LibraryStorage, safe_folder_name


async def test_queue_stop_cancels_an_idle_worker_immediately() -> None:
    queue = ProcessingQueue(None, lambda: None)  # type: ignore[arg-type]
    queue.start()
    await queue.stop()
    assert queue._task is None


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


def test_rescan_rebuilds_index_from_current_library_contents(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    stale = VideoMeta(video_id="stale-id", source_url="https://example.com/stale", title="Stale", channel="Old", status="complete")
    stale_folder = storage.create_video_folder(stale)
    storage.save_meta(stale, stale_folder)

    live = VideoMeta(video_id="live-id", source_url="https://example.com/live", title="Live", channel="New", status="complete")
    live_folder = storage.create_video_folder(live)
    storage.save_meta(live, live_folder)

    storage.delete_video("stale-id", delete_files=False)
    final = LibraryStorage(tmp_path)

    scanned = final.rescan()

    assert scanned == 1
    assert final.get_video("stale-id") is None
    assert final.get_video("live-id") is not None


def test_storage_exposes_each_immutable_transcript_artifact(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    original = TranscriptInfo(file="transcripts/original-en-original-1.md", language="en", kind="original", source="youtube", role="original")
    localized = TranscriptInfo(file="transcripts/settings-ru-author-2.md", language="ru", kind="author", source="youtube", role="settings")
    meta = VideoMeta(video_id="Gn64NNr3bqU", source_url="https://youtu.be/Gn64NNr3bqU", title="Two transcripts", transcript=original, transcripts=[original, localized])
    folder = storage.create_video_folder(meta)
    (folder / "transcripts").mkdir()
    (folder / original.file).write_text("# Original\n\nEnglish", encoding="utf-8")
    (folder / localized.file).write_text("# Localized\n\nРусский", encoding="utf-8")
    storage.save_meta(meta, folder)

    detail = storage.get_video(meta.video_id)
    assert detail is not None
    assert detail.transcript_markdown.endswith("English")
    assert detail.transcript_markdowns[localized.file].endswith("Русский")
    assert [item.role for item in detail.meta.transcripts] == ["original", "settings"]


def test_repeated_transcript_export_never_overwrites_an_artifact(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ytsum.queue.utc_now", lambda: "2026-08-15T00:00:00Z")
    meta = VideoMeta(video_id="Gn64NNr3bqU", source_url="https://youtu.be/Gn64NNr3bqU", title="Immutable")
    queue = ProcessingQueue(None, None)  # type: ignore[arg-type]
    from ytsum.models import TranscriptSegment

    first = queue._write_transcript(meta, tmp_path, "original", "en", "original", "youtube", None, [TranscriptSegment(start=0, end=1, text="first")])
    second = queue._write_transcript(meta, tmp_path, "original", "en", "original", "youtube", None, [TranscriptSegment(start=0, end=1, text="second")])

    assert first.file != second.file
    assert (tmp_path / first.file).read_text(encoding="utf-8").endswith("first\n")
    assert (tmp_path / second.file).read_text(encoding="utf-8").endswith("second\n")


def test_jobs_are_persistent_and_ordered(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    first = storage.enqueue("Gn64NNr3bqU", "https://youtu.be/Gn64NNr3bqU")
    second = storage.enqueue("dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ")
    assert [job.id for job in storage.list_jobs()[:2]] == [first.id, second.id]
    claimed = storage.next_job()
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == "processing"


def test_next_job_can_claim_independent_queue_lanes(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    download = storage.enqueue("download", "https://youtu.be/download", kind="process")
    llm = storage.enqueue("llm", "https://youtu.be/llm", kind="summarize")

    claimed_llm = storage.next_job(("summarize", "prompt"))
    assert claimed_llm is not None
    assert claimed_llm.id == llm.id
    claimed_download = storage.next_job(("process", "refresh"))
    assert claimed_download is not None
    assert claimed_download.id == download.id


def test_summary_progress_fields_and_stage_journal_survive_storage_round_trip(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    job = storage.enqueue("Gn64NNr3bqU", "https://youtu.be/Gn64NNr3bqU", kind="summarize")
    event = JobStageEvent(stage="summary-map", message="Summarizing source part 1/2", status="completed", requests_planned=3, requests_completed=1)
    storage.update_job(job.id, stage="summary-map", requests_planned=3, requests_completed=1, summary_source="transcript.md", provider_id="local", provider_name="Local Ollama", model="llama-test", stage_log_json=[event.model_dump(mode="json")])

    restored = storage.get_job(job.id)
    assert restored is not None
    assert (restored.requests_completed, restored.requests_planned) == (1, 3)
    assert restored.summary_source == "transcript.md"
    assert restored.provider_name == "Local Ollama"
    assert restored.stage_log[0].message == event.message


def test_playlist_import_deduplicates_jobs_and_preserves_membership(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    playlist = PlaylistMeta(id="PL12345", title="Research", source_url="https://www.youtube.com/playlist?list=PL12345")
    entries = [("Gn64NNr3bqU", "https://www.youtube.com/watch?v=Gn64NNr3bqU", 1), ("dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", 2)]
    jobs, existing = storage.import_playlist(playlist, entries)
    assert len(jobs) == 2
    assert existing == []
    jobs, existing = storage.import_playlist(playlist, entries)
    assert jobs == []
    assert existing == ["Gn64NNr3bqU", "dQw4w9WgXcQ"]
    assert len(storage.list_jobs()) == 2
    assert storage.get_video("Gn64NNr3bqU").meta.playlists[0].title == "Research"
    assert storage.list_playlists()[0]["video_count"] == 2


def test_finished_job_history_can_be_removed_without_touching_video_artifacts(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    video_id = "Gn64NNr3bqU"
    job = storage.enqueue(video_id, "https://youtu.be/Gn64NNr3bqU")
    storage.update_job(job.id, status="complete", stage="complete", progress=1)
    artifact = tmp_path / "video-artifact.md"
    artifact.write_text("keep me", encoding="utf-8")
    log_path = storage.logs_dir / f"{job.id}.log"
    log_path.write_text("job log", encoding="utf-8")

    assert storage.delete_finished_job(job.id) is True
    assert storage.get_job(job.id) is None
    assert artifact.read_text(encoding="utf-8") == "keep me"
    assert not log_path.exists()


def test_active_job_history_cannot_be_removed(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    job = storage.enqueue("Gn64NNr3bqU", "https://youtu.be/Gn64NNr3bqU")

    assert storage.delete_finished_job(job.id) is None
    assert storage.get_job(job.id) is not None


def test_archiving_hides_video_without_removing_its_artifacts(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    meta = VideoMeta(video_id="Gn64NNr3bqU", source_url="https://youtu.be/Gn64NNr3bqU", title="Keep the files")
    folder = storage.create_video_folder(meta)
    artifact = folder / "summary.md"
    artifact.write_text("Kept", encoding="utf-8")
    storage.save_meta(meta, folder)

    archived = storage.patch_video(meta.video_id, None, None, archived=True)
    assert archived and archived.archived
    assert storage.list_videos() == []
    assert [video["video_id"] for video in storage.list_videos(archived=True)] == [meta.video_id]
    assert artifact.read_text(encoding="utf-8") == "Kept"

    restored = storage.patch_video(meta.video_id, None, None, archived=False)
    assert restored and not restored.archived
    assert [video["video_id"] for video in storage.list_videos()] == [meta.video_id]


def test_archiving_survives_a_stale_background_metadata_save(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    meta = VideoMeta(video_id="Gn64NNr3bqU", source_url="https://youtu.be/Gn64NNr3bqU", title="Background work")
    folder = storage.create_video_folder(meta)
    storage.save_meta(meta, folder)
    stale_meta = storage.get_video(meta.video_id).meta

    storage.patch_video(meta.video_id, None, None, archived=True)
    stale_meta.status = "complete"  # Simulates a worker finishing after archiving.
    storage.save_meta(stale_meta, folder)

    assert storage.get_video(meta.video_id).meta.archived is True
    assert storage.list_videos() == []
    assert [video["video_id"] for video in storage.list_videos(archived=True)] == [meta.video_id]


def test_prompt_artifacts_are_loaded_only_from_a_video_artifacts_folder(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    meta = VideoMeta(video_id="Gn64NNr3bqU", source_url="https://youtu.be/Gn64NNr3bqU", title="Prompt result")
    folder = storage.create_video_folder(meta)
    artifact = PromptArtifact(id="job-1", file="artifacts/ideas-job-1.md", template_id="ideas", template_name="Идеи", provider_id="ollama", model="test", language="ru")
    (folder / "artifacts").mkdir()
    (folder / artifact.file).write_text("# Ideas\n", encoding="utf-8")
    meta.prompt_artifacts.append(artifact)
    storage.save_meta(meta, folder)

    detail = storage.get_video(meta.video_id)
    assert detail and [item.id for item in detail.prompt_artifacts] == ["job-1"]
    assert storage.read_prompt_artifact(meta.video_id, "job-1") == (artifact, "# Ideas\n")
