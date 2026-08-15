from __future__ import annotations

import shutil
import os
import signal
import subprocess
import sys
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import yt_dlp.version
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .context import ApplicationContext
from .downloader import YouTubeClient, is_playlist_url, normalize_youtube_url
from .git_update import GitUpdateError, pull_source_update, source_update_status
from .keychain import get_secret, set_secret
from .models import (
    AddVideosRequest,
    AppSettings,
    CreatePromptRequest,
    CreateSummaryRequest,
    CreateSpeechRequest,
    ProviderSecretRequest,
    ReorderJobsRequest,
    UpdateVideoRequest,
)
from .providers import ProviderClient, ProviderError
from .transcriber import MeetingTranscriberBridge
from .tts import MacSayTTS


_context: ApplicationContext | None = None


def context() -> ApplicationContext:
    global _context
    if _context is None:
        _context = ApplicationContext()
    return _context


@asynccontextmanager
async def lifespan(_: FastAPI):
    app_context = context()
    app_context.storage().rescan()
    app_context.storage().cleanup_logs(app_context.settings_repo.load().log_retention_days)
    app_context.queue.start()
    yield
    await app_context.queue.stop()


app = FastAPI(title="YT Sum Local API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
async def health() -> dict:
    settings = context().settings_repo.load()
    native_status = await MeetingTranscriberBridge(settings).health()
    cookie_file = Path(settings.cookie_file).expanduser() if settings.cookie_file else None
    jobs = context().storage().list_jobs()

    def queue_summary(kinds: set[str]) -> dict:
        lane = [job for job in jobs if job.kind in kinds]
        active = [job for job in lane if job.status == "processing"]
        queued = [job for job in lane if job.status == "queued"]
        return {
            "total": len(lane),
            "queued": len(queued),
            "processing": len(active),
            "completed": sum(job.status == "complete" for job in lane),
            "failed": sum(job.status == "attention" for job in lane),
            "cancelled": sum(job.status == "cancelled" for job in lane),
            "current_stage": active[0].stage if active else None,
            "current_video_id": active[0].video_id if active else None,
            "current_progress": active[0].progress if active else None,
        }
    return {
        "status": "ok",
        "queue_paused": context().queue.paused,
        "queues": {
            "download": queue_summary({"process", "refresh"}),
            "llm": queue_summary({"summarize", "prompt", "tts"}),
        },
        "library": str(context().storage().library_dir),
        "components": {
            "yt_dlp": {"ready": True, "version": yt_dlp.version.__version__},
            "ffmpeg": {"ready": shutil.which("ffmpeg") is not None},
            "native_transcriber": {"engine": settings.asr_engine, **native_status},
            "text_to_speech": {"ready": MacSayTTS(settings).ready(), "engine": settings.tts_engine},
            "cookies": {"ready": bool((cookie_file and cookie_file.exists()) or settings.cookie_browser), "browser": settings.cookie_browser or None},
        },
    }


@app.get("/api/videos")
def list_videos(
    query: str = "",
    status: str = "",
    favorite: bool | None = None,
    archived: bool = False,
    sort: str = "added_desc",
) -> dict:
    return {"items": context().storage().list_videos(query=query, status=status, favorite=favorite, archived=archived, sort=sort)}


@app.get("/api/playlists")
def list_playlists() -> dict:
    return {"items": context().storage().list_playlists()}


@app.post("/api/videos", status_code=202)
def add_videos(request: AddVideosRequest) -> dict:
    jobs = []
    existing = []
    errors = []
    seen: set[str] = set()
    for raw_url in request.urls:
        if is_playlist_url(raw_url):
            try:
                playlist = YouTubeClient(context().settings_repo.load()).extract_playlist(raw_url)
                added, already_present = context().storage().import_playlist(
                    playlist.meta,
                    [(entry.video_id, entry.source_url, entry.position) for entry in playlist.entries],
                )
                jobs.extend(job.model_dump(mode="json") for job in added)
                existing.extend(already_present)
            except Exception as error:
                errors.append({"url": raw_url, "error": str(error)})
            continue
        try:
            video_id, url = normalize_youtube_url(raw_url)
        except ValueError as error:
            errors.append({"url": raw_url, "error": str(error)})
            continue
        if video_id in seen:
            continue
        seen.add(video_id)
        if context().storage().video_exists(video_id):
            existing.append(video_id)
            continue
        context().storage().create_placeholder(video_id, url)
        jobs.append(context().storage().enqueue(video_id, url).model_dump(mode="json"))
    context().queue.notify()
    return {"jobs": jobs, "existing": existing, "errors": errors}


@app.get("/api/videos/{video_id}")
def get_video(video_id: str) -> dict:
    detail = context().storage().get_video(video_id)
    if not detail:
        raise HTTPException(404, "Video not found")
    return detail.model_dump(mode="json")


@app.get("/api/videos/{video_id}/thumbnail")
def get_thumbnail(video_id: str):
    detail = context().storage().get_video(video_id)
    if not detail or not detail.folder or not detail.meta.thumbnail_file:
        raise HTTPException(404, "Thumbnail not found")
    path = Path(detail.folder) / detail.meta.thumbnail_file
    if not path.exists() or path.parent.resolve() != Path(detail.folder).resolve():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(path)


def artifact_folder(video_id: str) -> Path:
    """Return a video's artifact directory only when it remains inside the library."""
    detail = context().storage().get_video(video_id)
    if not detail or detail.meta.video_id != video_id or not detail.folder:
        raise HTTPException(404, "Video artifacts not found")

    library_dir = context().storage().library_dir.resolve()
    folder = Path(detail.folder).resolve()
    try:
        folder.relative_to(library_dir)
    except ValueError as error:
        raise HTTPException(403, "Video artifacts are outside the library") from error
    if folder == library_dir or not folder.is_dir():
        raise HTTPException(404, "Video artifacts not found")
    return folder


@app.post("/api/videos/{video_id}/folder/open")
def open_video_folder(video_id: str) -> dict:
    folder = artifact_folder(video_id)
    try:
        subprocess.run(["open", str(folder)], check=True, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        raise HTTPException(502, "Could not open the artifacts folder in Finder") from error
    return {"opened": True}


@app.patch("/api/videos/{video_id}")
def patch_video(video_id: str, request: UpdateVideoRequest) -> dict:
    meta = context().storage().patch_video(video_id, request.favorite, request.tags, request.archived)
    if not meta:
        raise HTTPException(404, "Video not found")
    return meta.model_dump(mode="json")


@app.post("/api/videos/{video_id}/refresh", status_code=202)
def refresh_video(video_id: str) -> dict:
    detail = context().storage().get_video(video_id)
    if not detail:
        raise HTTPException(404, "Video not found")
    job = context().storage().enqueue(video_id, detail.meta.source_url, kind="refresh")
    context().queue.notify()
    return job.model_dump(mode="json")


@app.post("/api/videos/{video_id}/summaries", status_code=202)
def create_summary(video_id: str, request: CreateSummaryRequest) -> dict:
    detail = context().storage().get_video(video_id)
    if not detail or not detail.transcript_markdown:
        raise HTTPException(409, "Transcript is not ready")
    overrides = {key: value for key, value in request.model_dump().items() if value is not None}
    job = context().storage().enqueue(video_id, detail.meta.source_url, kind="summarize", overrides=overrides)
    context().queue.notify()
    return job.model_dump(mode="json")


@app.post("/api/videos/{video_id}/prompts", status_code=202)
def create_prompt(video_id: str, request: CreatePromptRequest) -> dict:
    detail = context().storage().get_video(video_id)
    if not detail or not detail.transcript_markdown:
        raise HTTPException(409, "Transcript is not ready")
    if not any(item.id == request.template_id for item in context().settings_repo.load().templates):
        raise HTTPException(404, "Prompt template not found")
    overrides = {key: value for key, value in request.model_dump().items() if value is not None}
    job = context().storage().enqueue(video_id, detail.meta.source_url, kind="prompt", overrides=overrides)
    context().queue.notify()
    return job.model_dump(mode="json")


@app.get("/api/videos/{video_id}/prompts/{artifact_id}")
def get_prompt_artifact(video_id: str, artifact_id: str) -> dict:
    result = context().storage().read_prompt_artifact(video_id, artifact_id)
    if not result:
        raise HTTPException(404, "Prompt artifact not found")
    artifact, markdown = result
    return {"artifact": artifact.model_dump(mode="json"), "markdown": markdown}


@app.post("/api/videos/{video_id}/speech", status_code=202)
def create_speech(video_id: str, request: CreateSpeechRequest) -> dict:
    detail = context().storage().get_video(video_id)
    if not detail:
        raise HTTPException(404, "Video not found")
    markdown = detail.transcript_markdown if request.artifact == "transcript" else detail.summary_markdown
    if not markdown.strip():
        raise HTTPException(409, f"{request.artifact.capitalize()} is not ready")
    job = context().storage().enqueue(video_id, detail.meta.source_url, kind="tts", overrides={"artifact": request.artifact})
    context().queue.notify()
    return job.model_dump(mode="json")


@app.get("/api/videos/{video_id}/speech/{artifact}")
def get_speech(video_id: str, artifact: str):
    if artifact not in {"transcript", "summary"}:
        raise HTTPException(404, "Audio not found")
    detail = context().storage().get_video(video_id)
    if not detail or not detail.folder:
        raise HTTPException(404, "Audio not found")
    item = next((item for item in detail.meta.audio_artifacts if item.artifact == artifact), None)
    if not item:
        raise HTTPException(404, "Audio not found")
    path = Path(detail.folder) / item.file
    if not path.exists() or path.parent.resolve() != Path(detail.folder).resolve():
        raise HTTPException(404, "Audio not found")
    return FileResponse(path, media_type="audio/mp4")


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str, delete_files: bool = Query(False)) -> dict:
    if not context().storage().delete_video(video_id, delete_files):
        raise HTTPException(404, "Video not found")
    return {"deleted": True, "files_deleted": delete_files}


@app.get("/api/jobs")
def list_jobs() -> dict:
    items = [job.model_dump(mode="json") for job in context().storage().list_jobs()]
    download = [item for item in items if item["kind"] in {"process", "refresh"}]
    llm = [item for item in items if item["kind"] in {"summarize", "prompt", "tts"}]
    return {"paused": context().queue.paused, "items": items, "download_items": download, "llm_items": llm}


@app.delete("/api/jobs/{job_id}")
def delete_finished_job(job_id: str) -> dict:
    deleted = context().storage().delete_finished_job(job_id)
    if deleted is False:
        raise HTTPException(404, "Job not found")
    if deleted is None:
        raise HTTPException(409, "Only completed or failed jobs can be removed")
    return {"deleted": True}


@app.post("/api/jobs/pause")
def pause_jobs() -> dict:
    context().queue.pause()
    return {"paused": True}


@app.post("/api/jobs/resume")
def resume_jobs() -> dict:
    context().queue.resume()
    return {"paused": False}


@app.post("/api/jobs/stop")
def stop_jobs() -> dict:
    """Cancel every queued or currently running job without deleting history."""
    return {"cancelled": context().queue.cancel_all()}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    if not context().storage().get_job(job_id):
        raise HTTPException(404, "Job not found")
    context().queue.cancel(job_id)
    return {"cancelled": True}


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str) -> dict:
    previous = context().storage().get_job(job_id)
    if not previous:
        raise HTTPException(404, "Job not found")
    job = context().storage().enqueue(previous.video_id, previous.source_url, kind=previous.kind, overrides=previous.overrides)
    context().queue.notify()
    return job.model_dump(mode="json")


@app.post("/api/jobs/reorder")
def reorder_jobs(request: ReorderJobsRequest) -> dict:
    context().storage().reorder_jobs(request.job_ids)
    return {"updated": True}


@app.get("/api/settings")
def get_settings() -> dict:
    settings = context().settings_repo.load()
    for provider in settings.providers:
        provider.has_api_key = get_secret(provider.id) is not None
    return settings.model_dump(mode="json")


@app.put("/api/settings")
def put_settings(settings: AppSettings) -> dict:
    return context().save_settings(settings).model_dump(mode="json")


@app.post("/api/providers/{provider_id}/secret")
def save_provider_secret(provider_id: str, request: ProviderSecretRequest) -> dict:
    provider = next((item for item in context().settings_repo.load().providers if item.id == provider_id), None)
    if not provider:
        raise HTTPException(404, "Provider not found")
    set_secret(provider_id, request.api_key)
    return {"saved": bool(request.api_key)}


@app.post("/api/providers/{provider_id}/models")
async def provider_models(provider_id: str) -> dict:
    provider = next((item for item in context().settings_repo.load().providers if item.id == provider_id), None)
    if not provider:
        raise HTTPException(404, "Provider not found")
    try:
        models = await ProviderClient(provider).list_models()
    except ProviderError as error:
        raise HTTPException(502, str(error)) from error
    return {"items": models}


@app.get("/api/providers/status")
def provider_statuses() -> dict:
    settings = context().settings_repo.load()
    return {"items": ProviderClient.statuses(settings.providers)}


@app.post("/api/library/rescan")
def rescan_library() -> dict:
    return {"indexed": context().storage().rescan()}


@app.post("/api/system/yt-dlp/update")
async def update_yt_dlp() -> dict:
    def install() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "--pre", "yt-dlp"],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

    result = await asyncio.to_thread(install)
    if result.returncode != 0:
        raise HTTPException(500, (result.stderr or result.stdout)[-1500:])
    return {"updated": True, "restart_required": True, "message": (result.stdout or "yt-dlp updated")[-1000:]}


@app.get("/api/system/source-update")
async def get_source_update_status() -> dict:
    try:
        return await asyncio.to_thread(source_update_status)
    except GitUpdateError as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/system/source-update/pull")
async def pull_source() -> dict:
    try:
        return await asyncio.to_thread(pull_source_update)
    except GitUpdateError as error:
        raise HTTPException(409, str(error)) from error


@app.post("/api/system/restart")
async def restart_application() -> dict:
    if os.environ.get("YTSUM_RESTART_ALLOWED") != "1":
        raise HTTPException(409, "Restart is available only when the app is started with scripts/dev.sh.")

    async def stop_after_response() -> None:
        await asyncio.sleep(0.25)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(stop_after_response())
    return {"restarting": True, "message": "The API is stopping now; its supervisor will start it again."}
