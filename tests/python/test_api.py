from pathlib import Path

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
