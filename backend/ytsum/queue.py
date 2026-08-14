from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Callable

from .captions import parse_caption_file, transcript_markdown
from .downloader import YouTubeClient
from .models import AppSettings, JobRecord, SummaryVersion, TranscriptInfo, VideoMeta, utc_now
from .settings import SettingsRepository
from .storage import LibraryStorage
from .summarizer import Summarizer
from .transcriber import MeetingTranscriberBridge


class JobCancelled(RuntimeError):
    pass


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:60] or "item"


class ProcessingQueue:
    def __init__(self, settings_repo: SettingsRepository, storage_provider: Callable[[], LibraryStorage]) -> None:
        self.settings_repo = settings_repo
        self.storage_provider = storage_provider
        self.paused = False
        self._wake = asyncio.Event()
        self._stopping = False
        self._cancelled: set[str] = set()
        self._task: asyncio.Task | None = None

    @property
    def storage(self) -> LibraryStorage:
        return self.storage_provider()

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._run(), name="yt-sum-worker")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task:
            await self._task

    def notify(self) -> None:
        self._wake.set()

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False
        self.notify()

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)
        job = self.storage.get_job(job_id)
        if job and job.status == "queued":
            self.storage.update_job(job_id, status="cancelled", stage="cancelled")

    async def _run(self) -> None:
        while not self._stopping:
            if self.paused:
                self._wake.clear()
                await self._wake.wait()
                continue
            job = self.storage.next_job()
            if not job:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=2)
                except TimeoutError:
                    pass
                continue
            await self._execute(job)

    def _check_cancelled(self, job: JobRecord) -> None:
        if job.id in self._cancelled:
            raise JobCancelled("Cancelled by user")

    def _log(self, job: JobRecord, message: str) -> None:
        message = re.sub(r"(?i)(authorization|api[_ -]?key|bearer)\s*[:=]\s*\S+", r"\1: [redacted]", message)
        job.log.append(f"{utc_now()} {message}")
        job = self.storage.update_job(job.id, log_json=job.log) or job
        self.storage.write_job_log(job)

    def _stage(self, job: JobRecord, stage: str, progress: float) -> None:
        job.stage = stage
        job.progress = progress
        self.storage.update_job(job.id, stage=stage, progress=progress)

    async def _execute(self, job: JobRecord) -> None:
        settings = self.settings_repo.load()
        work_dir = self.storage.work_dir / job.id
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._log(job, f"Starting {job.kind} job for {job.video_id}")
            if job.kind in {"process", "refresh"}:
                await self._prepare_transcript(job, settings, work_dir)
            self._check_cancelled(job)
            await self._create_summary(job, settings)
            self.storage.update_job(job.id, status="complete", stage="complete", progress=1, error=None)
            self._log(job, "Job completed")
        except JobCancelled as error:
            self.storage.update_job(job.id, status="cancelled", stage="cancelled", error=str(error))
            self._log(job, str(error))
        except Exception as error:
            self.storage.update_job(job.id, status="attention", stage="attention", error=str(error), attempts=job.attempts + 1)
            detail = self.storage.get_video(job.video_id)
            if detail and detail.folder:
                detail.meta.status = "attention"
                detail.meta.error = str(error)
                self.storage.save_meta(detail.meta, Path(detail.folder))
            self._log(job, f"Job requires attention: {error}")
        finally:
            self._cancelled.discard(job.id)
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)

    async def _prepare_transcript(self, job: JobRecord, settings: AppSettings, work_dir: Path) -> None:
        client = YouTubeClient(settings)
        self._stage(job, "metadata", 0.08)
        extracted = await asyncio.to_thread(client.extract, job.source_url)
        self._check_cancelled(job)
        previous = self.storage.read_meta(job.video_id)
        meta = VideoMeta(
            video_id=extracted.video_id,
            source_url=extracted.url,
            title=extracted.title,
            channel=extracted.channel,
            published_at=extracted.published_at,
            duration_seconds=extracted.duration_seconds,
            thumbnail_url=extracted.thumbnail_url,
            status="processing",
            favorite=previous[0].favorite if previous else False,
            tags=previous[0].tags if previous else [],
            summary_versions=previous[0].summary_versions if previous else [],
            current_summary=previous[0].current_summary if previous else None,
            added_at=previous[0].added_at if previous else utc_now(),
            available_languages=extracted.available_languages,
        )
        folder = self.storage.create_video_folder(meta)
        self.storage.save_meta(meta, folder)

        self._stage(job, "thumbnail", 0.14)
        thumbnail = await asyncio.to_thread(client.cache_thumbnail, extracted, folder)
        if thumbnail:
            meta.thumbnail_file = thumbnail.name
            self.storage.save_meta(meta, folder)

        self._stage(job, "transcript-selection", 0.22)
        choice = client.choose_transcript(extracted)
        if choice:
            self._log(job, f"Selected {choice.kind} transcript language {choice.language}")
            self._stage(job, "subtitle-download", 0.32)
            caption_file = await asyncio.to_thread(client.download_subtitle, extracted, choice, work_dir)
            segments = parse_caption_file(caption_file)
            language = choice.language
            kind = choice.kind
            engine = None
        else:
            self._log(job, "No usable YouTube transcript; switching to local audio transcription")
            self._stage(job, "audio-download", 0.30)
            audio_path = await asyncio.to_thread(client.download_audio, extracted, work_dir)
            self._check_cancelled(job)
            self._stage(job, "transcribing", 0.50)
            segments = await MeetingTranscriberBridge(settings).transcribe(audio_path)
            language = settings.asr_language or extracted.original_language or "auto"
            kind = "local_asr"
            engine = settings.asr_engine
            if settings.keep_audio:
                shutil.copy2(audio_path, folder / "audio.wav")

        if not segments:
            raise RuntimeError("Transcript is empty")
        markdown = transcript_markdown(video_id=meta.video_id, title=meta.title, language=language, kind=kind, engine=engine, segments=segments)
        atomic_write(folder / "transcript.md", markdown)
        meta.transcript = TranscriptInfo(language=language, kind=kind, engine=engine, segment_count=len(segments))
        meta.status = "transcript_ready"
        meta.error = None
        self.storage.save_meta(meta, folder)
        self.storage.update_search(meta.video_id)
        self._stage(job, "transcript-ready", 0.68)

    async def _create_summary(self, job: JobRecord, settings: AppSettings) -> None:
        detail = self.storage.get_video(job.video_id)
        if not detail or not detail.folder or not detail.transcript_markdown:
            raise RuntimeError("Transcript is not ready")
        overrides = job.overrides
        provider_id = overrides.get("provider_id") or settings.active_provider_id
        provider = next((item for item in settings.providers if item.id == provider_id), None)
        if not provider:
            raise RuntimeError(f"Summary provider '{provider_id}' not found")
        model = overrides.get("model") or provider.model
        if not model:
            raise RuntimeError("Choose a summary model in Settings")
        template_id = overrides.get("template_id") or settings.summary_template_id
        template = next((item for item in settings.templates if item.id == template_id), None)
        if not template:
            raise RuntimeError(f"Summary template '{template_id}' not found")
        language = overrides.get("language") or settings.summary_language
        mode = overrides.get("mode") or settings.summary_mode
        self._stage(job, "summarizing", 0.72)
        result = await Summarizer(settings, provider, template).run(detail.transcript_markdown, language=language, model=model, mode=mode)
        folder = Path(detail.folder)
        history_dir = folder / "summary-history"
        history_dir.mkdir(exist_ok=True)
        if (folder / "summary.md").exists() and detail.meta.current_summary:
            previous = detail.meta.current_summary
            history_name = f"{safe_component(previous.generated_at)}-{safe_component(previous.model)}-{safe_component(previous.template_id)}.md"
            shutil.copy2(folder / "summary.md", history_dir / history_name)
            previous.file = f"summary-history/{history_name}"
            detail.meta.summary_versions.append(previous)
        atomic_write(folder / "summary.md", result.markdown)
        detail.meta.current_summary = SummaryVersion(file="summary.md", provider_id=provider.id, model=model, template_id=template.id, language=language, mode=mode)
        detail.meta.summary_stale = False
        detail.meta.status = "complete"
        detail.meta.error = None
        self.storage.save_meta(detail.meta, folder)
        self.storage.update_search(job.video_id)
        self._log(job, f"Summary created with {provider.name}/{model} in {result.request_count} request(s)")
