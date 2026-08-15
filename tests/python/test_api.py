from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient


def test_local_api_adds_valid_urls_without_network(monkeypatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    library_dir = tmp_path / "library"
    monkeypatch.setenv("YTSUM_STATE_DIR", str(state_dir))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(library_dir))

    from ytsum import api

    api._context = None
    with TestClient(api.app) as client:
        assert client.post("/api/jobs/pause").json() == {"paused": True}
        response = client.post("/api/videos", json={"urls": ["https://youtu.be/Gn64NNr3bqU"]})
        assert response.status_code == 202
        assert len(response.json()["jobs"]) == 1
        videos = client.get("/api/videos").json()["items"]
        assert videos[0]["video_id"] == "Gn64NNr3bqU"
        assert videos[0]["status"] == "queued"


def test_local_api_reports_invalid_url(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))

    from ytsum import api

    api._context = None
    with TestClient(api.app) as client:
        client.post("/api/jobs/pause")
        response = client.post("/api/videos", json={"urls": ["https://youtube.com/playlist?list=abc"]})
        assert response.status_code == 202
        assert response.json()["jobs"] == []
        assert response.json()["errors"]


def test_local_api_imports_playlist_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))
    from ytsum import api
    from ytsum.downloader import ExtractedPlaylist, PlaylistEntry
    from ytsum.models import PlaylistMeta

    def extract_playlist(self, url):
        return ExtractedPlaylist(
            meta=PlaylistMeta(id="PL12345", title="Imported list", source_url="https://www.youtube.com/playlist?list=PL12345"),
            entries=[PlaylistEntry(video_id="Gn64NNr3bqU", source_url="https://www.youtube.com/watch?v=Gn64NNr3bqU", position=1)],
        )

    monkeypatch.setattr(api.YouTubeClient, "extract_playlist", extract_playlist)
    api._context = None
    with TestClient(api.app) as client:
        client.post("/api/jobs/pause")
        first = client.post("/api/videos", json={"urls": ["https://youtube.com/playlist?list=PL12345"]}).json()
        second = client.post("/api/videos", json={"urls": ["https://youtube.com/playlist?list=PL12345"]}).json()
        assert len(first["jobs"]) == 1
        assert second["jobs"] == []
        assert client.get("/api/playlists").json()["items"][0]["title"] == "Imported list"


def test_speech_api_requires_ready_artifact_and_enqueues(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))
    from ytsum import api
    from ytsum.models import TranscriptInfo, VideoMeta

    api._context = None
    with TestClient(api.app) as client:
        client.post("/api/jobs/pause")
        storage = api.context().storage()
        meta = VideoMeta(video_id="Gn64NNr3bqU", source_url="https://youtu.be/Gn64NNr3bqU", title="Test", transcript=TranscriptInfo(language="en", kind="author", segment_count=1))
        folder = storage.create_video_folder(meta)
        (folder / "transcript.md").write_text("# Transcript\n\nHello", encoding="utf-8")
        storage.save_meta(meta, folder)
        response = client.post("/api/videos/Gn64NNr3bqU/speech", json={"artifact": "transcript"})
        assert response.status_code == 202
        assert response.json()["kind"] == "tts"
        missing = client.post("/api/videos/Gn64NNr3bqU/speech", json={"artifact": "summary"})
        assert missing.status_code == 409


def test_source_update_status_is_exposed_without_running_a_pull(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))

    from ytsum import api

    api._context = None
    expected = {
        "available": True,
        "clean": False,
        "branch": "main",
        "upstream": "origin/main",
        "ahead": 0,
        "behind": 2,
        "can_pull": False,
        "diagnostic": "Local changes detected.",
    }
    monkeypatch.setattr(api, "source_update_status", lambda: expected)
    with TestClient(api.app) as client:
        response = client.get("/api/system/source-update")

    assert response.status_code == 200
    assert response.json() == expected


def test_health_includes_meeting_transcriber_address_and_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))

    from ytsum import api

    async def available(_self):
        return {"ready": True, "address": "http://127.0.0.1:9876", "state": "idle", "reason": None}

    monkeypatch.setattr(api.MeetingTranscriberBridge, "health", available)
    api._context = None
    with TestClient(api.app) as client:
        component = client.get("/api/health").json()["components"]["native_transcriber"]

    assert component["ready"] is True
    assert component["address"] == "http://127.0.0.1:9876"
    assert component["state"] == "idle"


def test_provider_pool_settings_persist_and_expose_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))

    from ytsum import api

    api._context = None
    with TestClient(api.app) as client:
        settings = client.get("/api/settings").json()
        settings["parallel_summary_sources"] = True
        settings["providers"][0]["enabled"] = False
        assert client.put("/api/settings", json=settings).status_code == 200
        reloaded = client.get("/api/settings").json()
        assert reloaded["parallel_summary_sources"] is True
        assert reloaded["providers"][0]["enabled"] is False
        statuses = client.get("/api/providers/status").json()["items"]
        assert {item["id"] for item in statuses} >= {"ollama", "openai-compatible"}
        assert all("requests_in_window" in item and "in_flight" in item for item in statuses)


def test_local_api_removes_only_finished_job_history(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))
    from ytsum import api

    api._context = None
    with TestClient(api.app) as client:
        client.post("/api/jobs/pause")
        job = client.post("/api/videos", json={"urls": ["https://youtu.be/Gn64NNr3bqU"]}).json()["jobs"][0]
        assert client.delete(f"/api/jobs/{job['id']}").status_code == 409

        api.context().storage().update_job(job["id"], status="attention", stage="failed", error="network error")
        assert client.delete(f"/api/jobs/{job['id']}").json() == {"deleted": True}
        assert client.get("/api/jobs").json()["items"] == []
        assert client.delete(f"/api/jobs/{job['id']}").status_code == 404


def test_local_api_can_archive_and_restore_a_video(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))
    from ytsum import api

    api._context = None
    with TestClient(api.app) as client:
        client.post("/api/jobs/pause")
        client.post("/api/videos", json={"urls": ["https://youtu.be/Gn64NNr3bqU"]})
        assert client.patch("/api/videos/Gn64NNr3bqU", json={"archived": True}).json()["archived"] is True
        assert client.get("/api/videos").json()["items"] == []
        assert client.get("/api/videos?archived=true").json()["items"][0]["video_id"] == "Gn64NNr3bqU"
        assert client.patch("/api/videos/Gn64NNr3bqU", json={"archived": False}).json()["archived"] is False


def test_local_api_opens_only_artifact_folders_inside_the_library(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))
    from ytsum import api
    from ytsum.models import VideoMeta

    api._context = None
    opened: list[list[str]] = []

    def open_folder(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        opened.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(api.subprocess, "run", open_folder)
    with TestClient(api.app) as client:
        storage = api.context().storage()
        meta = VideoMeta(video_id="Gn64NNr3bqU", source_url="https://youtu.be/Gn64NNr3bqU", title="Local artifact")
        folder = storage.create_video_folder(meta)
        storage.save_meta(meta, folder)

        assert client.post(f"/api/videos/{meta.video_id}/folder/open").json() == {"opened": True}
        assert opened == [["open", str(folder.resolve())]]

        outside = tmp_path / "outside"
        shutil.copytree(folder, outside)
        shutil.rmtree(folder)
        folder.symlink_to(outside, target_is_directory=True)
        response = client.post(f"/api/videos/{meta.video_id}/folder/open")
        assert response.status_code == 403
        assert len(opened) == 1


def test_local_api_enqueues_a_standalone_prompt_after_transcript_is_ready(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YTSUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("YTSUM_LIBRARY_DIR", str(tmp_path / "library"))
    from ytsum import api
    from ytsum.models import TranscriptInfo, VideoMeta

    api._context = None
    with TestClient(api.app) as client:
        client.post("/api/jobs/pause")
        storage = api.context().storage()
        meta = VideoMeta(video_id="Gn64NNr3bqU", source_url="https://youtu.be/Gn64NNr3bqU", title="Ready", transcript=TranscriptInfo(file="transcript.md", language="en", kind="author"))
        folder = storage.create_video_folder(meta)
        (folder / "transcript.md").write_text("# Transcript\n\nReady text", encoding="utf-8")
        storage.save_meta(meta, folder)

        response = client.post("/api/videos/Gn64NNr3bqU/prompts", json={"template_id": "ideas"})
        assert response.status_code == 202
        assert response.json()["kind"] == "prompt"
        assert response.json()["overrides"]["template_id"] == "ideas"
