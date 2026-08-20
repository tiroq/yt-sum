from __future__ import annotations

import asyncio
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from .captions import SubtitleChoice, parse_caption_file, transcript_markdown
from .downloader import YouTubeClient
from .models import (
    AppSettings,
    AudioArtifact,
    JobRecord,
    JobStageEvent,
    PromptArtifact,
    SummaryVersion,
    TranscriptInfo,
    VideoMeta,
    utc_now,
)
from .pipeline import ResourceCoordinator
from .settings import SettingsRepository
from .storage import LibraryStorage
from .summarizer import Summarizer, SummaryProgress
from .transcriber import MeetingTranscriberBridge
from .tts import MacSayTTS, markdown_to_speech


class JobCancelled(RuntimeError):
    pass


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:60] or "item"


def transcript_filename(role: str, language: str, kind: str, generated_at: str) -> str:
    return f"transcripts/{role}-{safe_component(language)}-{safe_component(kind)}-{safe_component(generated_at)}.md"


class ProcessingQueue:
    def __init__(
        self,
        settings_repo: SettingsRepository,
        storage_provider: Callable[[], LibraryStorage],
    ) -> None:
        self.settings_repo = settings_repo
        self.storage_provider = storage_provider
        self.paused = False
        self._wake = asyncio.Event()
        self._resume = asyncio.Event()
        self._resume.set()
        self._stopping = False
        self._cancelled: set[str] = set()
        self._task: asyncio.Task | None = None
        self._download_tasks: list[asyncio.Task] = []
        self._llm_tasks: list[asyncio.Task] = []
        self._llm_target = 1
        self._tts_tasks: list[asyncio.Task] = []
        self._resize_task: asyncio.Task | None = None
        self._active_jobs: dict[str, JobRecord] = {}
        self._job_tasks: dict[str, asyncio.Task] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self.resources = ResourceCoordinator(storage_provider)

    DOWNLOAD_KINDS = ("process", "refresh")
    LLM_KINDS = ("summarize", "prompt")
    TTS_KINDS = ("tts",)

    @property
    def storage(self) -> LibraryStorage:
        return self.storage_provider()

    def start(self) -> None:
        if not self._task:
            self._loop = asyncio.get_running_loop()
            self._stopping = False
            # Keep the queue lifecycle harmless for lightweight test doubles
            # that intentionally omit repositories.
            if self.settings_repo is None:
                self._task = asyncio.create_task(
                    asyncio.sleep(3600), name="yt-sum-test-worker"
                )
                return
            self._download_tasks = [
                asyncio.create_task(
                    self._run_downloads(index),
                    name=f"yt-sum-download-worker-{index + 1}",
                )
                for index in range(2)
            ]
            self._task = self._download_tasks[0]
            settings = self.settings_repo.load()
            worker_count = max(
                1,
                len(
                    [
                        provider
                        for provider in settings.providers
                        if provider.enabled and provider.model
                    ]
                ),
            )
            self._llm_target = worker_count
            self._llm_tasks = [
                asyncio.create_task(
                    self._run_llm(index), name=f"yt-sum-llm-worker-{index + 1}"
                )
                for index in range(worker_count)
            ]
            self._tts_tasks = [
                asyncio.create_task(self._run_tts(), name="yt-sum-tts-worker")
            ]

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        self._resume.set()
        if self._task or self._download_tasks or self._llm_tasks or self._tts_tasks:
            # LLM calls deliberately have a long request timeout. Shutdown
            # must not wait for one: the job is requeued for the next launch.
            for active_job in list(self._active_jobs.values()):
                self.storage.update_job(
                    active_job.id,
                    status="queued",
                    stage="queued",
                    error=None,
                )
                self._log(
                    active_job,
                    "Paused for application shutdown; will resume after restart",
                )
            tasks = [
                task
                for task in [
                    *self._download_tasks,
                    *self._llm_tasks,
                    *self._tts_tasks,
                    self._resize_task,
                ]
                if task
            ]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._task = None
            self._download_tasks = []
            self._llm_tasks = []
            self._tts_tasks = []
            self._resize_task = None
            self._active_jobs.clear()
            self._job_tasks.clear()

    def notify(self) -> None:
        self._wake.set()
        if self._task and not self._stopping and not self._resize_task:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # FastAPI's synchronous handlers may call notify from a
                # worker thread; the already-running pool remains valid.
                return
            self._resize_task = loop.create_task(
                self._sync_llm_workers(), name="yt-sum-llm-pool-sync"
            )

    async def _sync_llm_workers(self) -> None:
        try:
            if not self.settings_repo or self._stopping:
                return
            target = max(
                1,
                len(
                    [
                        provider
                        for provider in self.settings_repo.load().providers
                        if provider.enabled and provider.model
                    ]
                ),
            )
            self._llm_target = target
            self._llm_tasks = [task for task in self._llm_tasks if not task.done()]
            while len(self._llm_tasks) < target and not self._stopping:
                index = len(self._llm_tasks)
                self._llm_tasks.append(
                    asyncio.create_task(
                        self._run_llm(index), name=f"yt-sum-llm-worker-{index + 1}"
                    )
                )
        finally:
            self._resize_task = None

    def pause(self) -> None:
        self.paused = True
        self._resume.clear()

    def resume(self) -> None:
        self.paused = False
        self._resume.set()
        self.notify()

    async def _wait_until_resumed(self) -> None:
        while self.paused and not self._stopping:
            await self._resume.wait()

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)
        job = self.storage.get_job(job_id)
        if job and job.status in {"queued", "processing"}:
            if job.status == "queued":
                self.storage.transition_stage(
                    job.id,
                    job.stage,
                    "cancelled",
                    progress=job.progress,
                    message="Cancelled before execution",
                    error="Cancelled by user",
                )
            else:
                self.storage.update_job(job_id, execution_state="cancelling")
        task = self._job_tasks.get(job_id)
        if task and self._loop:
            self._loop.call_soon_threadsafe(task.cancel)

    def cancel_all(self) -> int:
        jobs = [
            job
            for job in self.storage.list_jobs()
            if job.status in {"queued", "processing"}
        ]
        for job in jobs:
            self.cancel(job.id)
        self.notify()
        return len(jobs)

    async def _run_lane(
        self, kinds: tuple[str, ...], worker_name: str, should_continue=lambda: True
    ) -> None:
        while not self._stopping:
            if not should_continue():
                return
            if self.paused:
                self._wake.clear()
                await self._wake.wait()
                continue
            job = self.storage.next_job(kinds)
            if not job:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=2)
                except TimeoutError:
                    pass
                continue
            self._active_jobs[worker_name] = job
            current_task = asyncio.current_task()
            if current_task:
                self._job_tasks[job.id] = current_task
            try:
                self._log(
                    job,
                    f"[WORKER:{worker_name}] Picked up job: kind={job.kind}, video_id={job.video_id}, source={job.source_url}",
                )
                await self._execute(job)
            except asyncio.CancelledError:
                if self._stopping:
                    raise
                self.storage.update_job(
                    job.id,
                    status="cancelled",
                    execution_state="cancelled",
                    error="Cancelled by user",
                )
                self.storage.finish_workflow(job.id, "cancelled")
                self._log(job, "[WORKER] Cancelled by user")
                self._event(job, "cancelled", "Cancelled by user", "failed")
            finally:
                self._job_tasks.pop(job.id, None)
                self._active_jobs.pop(worker_name, None)

    async def _run_downloads(self, index: int) -> None:
        await self._run_lane(self.DOWNLOAD_KINDS, f"downloads-{index}")

    async def _run_llm(self, index: int) -> None:
        await self._run_lane(
            self.LLM_KINDS, f"llm-{index}", lambda: index < self._llm_target
        )

    async def _run_tts(self) -> None:
        await self._run_lane(self.TTS_KINDS, "tts-0")

    def _check_cancelled(self, job: JobRecord) -> None:
        if job.id in self._cancelled:
            raise JobCancelled("Cancelled by user")

    def _log(self, job: JobRecord, message: str) -> None:
        message = re.sub(
            r"(?i)(authorization|api[_ -]?key|bearer)\s*[:=]\s*\S+",
            r"\1: [redacted]",
            message,
        )
        job.log.append(f"{utc_now()} {message}")
        job = self.storage.update_job(job.id, log_json=job.log) or job
        self.storage.write_job_log(job)

    def _event(
        self,
        job: JobRecord,
        stage: str,
        message: str,
        status: str = "progress",
        **changes: object,
    ) -> None:
        """Persist a structured, safe checkpoint for both API clients and the UI."""
        message = re.sub(
            r"(?i)(authorization|api[_ -]?key|bearer)\s*[:=]\s*\S+",
            r"\1: [redacted]",
            message,
        )
        event = JobStageEvent(
            stage=stage,
            message=message,
            status=status,  # type: ignore[arg-type]
            requests_planned=job.requests_planned,
            requests_completed=job.requests_completed,
        )
        job.stage_log.append(event)
        self.storage.update_job(
            job.id,
            stage_log_json=[item.model_dump(mode="json") for item in job.stage_log],
            **changes,
        )

    def _stage(self, job: JobRecord, stage: str, progress: float) -> None:
        job.stage = stage
        job.progress = progress
        self.storage.transition_stage(
            job.id,
            stage,
            "running",
            progress=progress,
            message=f"Stage started: {stage}",
        )
        self._event(job, stage, f"Stage started: {stage}", "started")

    def _complete_stage(
        self, job: JobRecord, stage: str, progress: float, message: str
    ) -> None:
        self.storage.transition_stage(
            job.id,
            stage,
            "succeeded",
            progress=progress,
            message=message,
        )

    async def _thread_call(self, function, *args):
        """Keep a resource lease until non-cancellable thread work really exits."""
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    async def _execute(self, job: JobRecord) -> None:
        workflow = (
            self.storage.get_workflow(job.workflow_id) if job.workflow_id else None
        )
        self._log(
            job,
            f"[EXECUTE] Loading settings: workflow_id={job.workflow_id}, has_workflow={workflow is not None}",
        )
        settings = (
            AppSettings.model_validate(workflow.settings_snapshot)
            if workflow and workflow.settings_snapshot
            else self.settings_repo.load()
        )
        if job.kind in {"summarize", "prompt"}:
            self._log(
                job,
                "[EXECUTE] Refreshing settings from current config for summarize/prompt job",
            )
            current = self.settings_repo.load()
            settings = settings.model_copy(
                update={
                    "providers": current.providers,
                    "active_provider_id": current.active_provider_id,
                    "parallel_summary_sources": current.parallel_summary_sources,
                }
            )
        work_dir = self.storage.work_dir / job.id
        work_dir.mkdir(parents=True, exist_ok=True)
        self._log(job, f"[EXECUTE] Work directory created: {work_dir}")
        try:
            self._event(job, "starting", f"Starting {job.kind} job", "started")
            self._log(
                job,
                f"[EXECUTE] Starting {job.kind} job for {job.video_id}, attempts={job.attempts}",
            )
            acquisition_job = job.kind in {"process", "refresh"}
            if acquisition_job:
                self._log(job, "[EXECUTE] Processing acquisition job (process/refresh)")
                await self._prepare_transcript(job, settings, work_dir)
            self._check_cancelled(job)
            if acquisition_job:
                self._log(job, "[EXECUTE] Acquisition complete, marking for summary")
                self.storage.update_job(
                    job.id,
                    status="complete",
                    stage="transcript-ready",
                    execution_state="succeeded",
                    progress=1,
                    error=None,
                )
                self._log(
                    job, "Transcript workflow completed; summary queued independently"
                )
                self.storage.enqueue(
                    job.video_id,
                    job.source_url,
                    kind="summarize",
                    workflow_id=job.workflow_id,
                )
                self.notify()
                return
            if job.kind == "tts":
                self._log(job, "[EXECUTE] Routing to TTS job")
                await self._create_speech(job, settings)
            elif job.kind == "prompt":
                self._log(job, "[EXECUTE] Routing to prompt artifact job")
                await self._create_prompt_artifact(job, settings)
            else:
                self._log(job, "[EXECUTE] Routing to summary job")
                await self._create_summary(job, settings)
            self.storage.update_job(
                job.id,
                status="complete",
                stage=job.stage,
                execution_state="succeeded",
                progress=1,
                error=None,
            )
            self.storage.finish_workflow(job.id, "complete")
            self._log(job, "Job completed")
            self._event(job, "complete", "Job completed", "completed")
        except JobCancelled as error:
            self.storage.update_job(
                job.id,
                status="cancelled",
                execution_state="cancelled",
                error=str(error),
            )
            self.storage.finish_workflow(job.id, "cancelled")
            self._log(job, str(error))
            self._event(job, "cancelled", str(error), "failed")
        except Exception as error:  # noqa: BLE001 - Intentional broad catch for error logging with context
            self._log(
                job,
                f"[ERROR] Job failed with exception: type={type(error).__name__}, message={error}",
            )
            import traceback

            tb_lines = traceback.format_exc().split("\n")
            for line in tb_lines[-5:]:  # Log last 5 lines of traceback for context
                if line.strip():
                    self._log(job, f"[ERROR_TRACEBACK] {line}")
            parent_stage = {"summarize": "summarizing", "prompt": "running-prompt"}.get(
                job.kind
            )
            if parent_stage:
                self._log(job, f"[ERROR] Transitioning stage {parent_stage} to failed")
                self.storage.transition_stage(
                    job.id,
                    parent_stage,
                    "failed",
                    progress=job.progress,
                    message=str(error),
                    error=str(error),
                )
            next_attempts = job.attempts + 1
            should_retry = (
                next_attempts <= settings.max_retry_attempts
                and job.kind in {"process", "refresh", "summarize", "prompt", "tts"}
            )
            if should_retry:
                self._log(
                    job,
                    f"[ERROR] Auto-retrying job: attempts {next_attempts}/{settings.max_retry_attempts}",
                )
                self.storage.update_job(
                    job.id,
                    status="queued",
                    execution_state="queued",
                    error=None,
                    attempts=next_attempts,
                )
                self.storage.finish_workflow(job.id, "queued")
                self.notify()
                self._log(job, f"[ERROR] Job re-queued for retry")
            else:
                self._log(
                    job,
                    f"[ERROR] Job requires attention (attempts exceeded: {next_attempts})",
                )
                self.storage.update_job(
                    job.id,
                    status="attention",
                    execution_state="failed",
                    error=str(error),
                    attempts=next_attempts,
                )
                self._log(
                    job,
                    f"[ERROR] Job updated with status=attention, attempts={next_attempts}",
                )
                self.storage.finish_workflow(job.id, "attention")
            detail = self.storage.get_video(job.video_id)
            if detail and detail.folder:
                self._log(
                    job,
                    f"[ERROR] Saving error state to meta: status={'partially_ready' if detail.transcript_markdown.strip() else 'attention'}",
                )
                detail.meta.status = (
                    "partially_ready"
                    if detail.transcript_markdown.strip()
                    else "attention"
                )
                detail.meta.error = str(error)
                self.storage.save_meta(detail.meta, Path(detail.folder))
            self._log(job, f"Job requires attention: {error}")
            self._event(job, "attention", f"Job requires attention: {error}", "failed")
        finally:
            self._cancelled.discard(job.id)
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)

    async def _prepare_transcript(
        self, job: JobRecord, settings: AppSettings, work_dir: Path
    ) -> None:
        self._log(job, f"[TRANSCRIPT] Starting transcript preparation: kind={job.kind}")
        checkpoint = self.storage.get_video(job.video_id)
        if (
            job.kind == "process"
            and checkpoint
            and checkpoint.transcript_markdown.strip()
        ):
            self._log(
                job,
                "[TRANSCRIPT] Verified transcript checkpoint found; YouTube acquisition skipped",
            )
            self.storage.transition_stage(
                job.id,
                "transcript-ready",
                "succeeded",
                progress=1,
                message="Existing transcript checkpoint verified",
            )
            return
        self._log(job, "[TRANSCRIPT] Creating YouTubeClient")
        client = YouTubeClient(settings)
        await self._wait_until_resumed()
        self._log(job, f"[TRANSCRIPT] Fetching metadata from {job.source_url}")
        async with self.resources.stage(
            job,
            "metadata",
            "yt_dlp",
            progress=0.08,
            message="Fetching metadata and transcript inventory",
        ):
            self._event(
                job, "metadata", f"Fetching metadata from {job.source_url}", "progress"
            )
            extracted = await self._thread_call(client.extract, job.source_url)
        self._log(
            job, f"[TRANSCRIPT] Metadata fetch completed: video_id={extracted.video_id}"
        )
        languages = (
            ", ".join(extracted.available_languages)
            if extracted.available_languages
            else "none reported"
        )
        duration = (
            f"{extracted.duration_seconds}s"
            if extracted.duration_seconds is not None
            else "unknown duration"
        )
        self._log(
            job,
            f"[TRANSCRIPT] Metadata extracted: title={extracted.title!r}; channel={extracted.channel or 'unknown'}; duration={duration}; languages={languages}",
        )
        self._event(
            job,
            "metadata",
            f"Metadata received: {extracted.title} · {extracted.channel or 'unknown channel'} · {duration}",
            "completed",
        )
        self._event(
            job, "metadata", f"Subtitle languages reported: {languages}", "progress"
        )
        self._check_cancelled(job)
        self._log(job, "[TRANSCRIPT] Checking for previous metadata")
        previous = self.storage.read_meta(job.video_id)
        existing = self.storage.get_video(job.video_id)
        previous_meta = (
            previous[0] if previous else (existing.meta if existing else None)
        )
        self._log(job, f"[TRANSCRIPT] Previous meta found: {previous_meta is not None}")
        meta = VideoMeta(
            video_id=extracted.video_id,
            source_url=extracted.url,
            title=extracted.title,
            channel=extracted.channel,
            published_at=extracted.published_at,
            duration_seconds=extracted.duration_seconds,
            thumbnail_url=extracted.thumbnail_url,
            status="processing",
            favorite=previous_meta.favorite if previous_meta else False,
            archived=previous_meta.archived if previous_meta else False,
            tags=previous_meta.tags if previous_meta else [],
            playlists=previous_meta.playlists if previous_meta else [],
            summary_versions=previous_meta.summary_versions if previous_meta else [],
            current_summary=previous_meta.current_summary if previous_meta else None,
            prompt_artifacts=previous_meta.prompt_artifacts if previous_meta else [],
            transcripts=previous_meta.transcripts if previous_meta else [],
            added_at=previous_meta.added_at if previous_meta else utc_now(),
            available_languages=extracted.available_languages,
        )
        self._log(job, "[TRANSCRIPT] Creating video folder")
        folder = self.storage.create_video_folder(meta)
        self.storage.save_meta(meta, folder)
        self._log(job, f"[TRANSCRIPT] Video folder created and meta saved: {folder}")

        await self._wait_until_resumed()
        self._log(job, "[TRANSCRIPT] Starting thumbnail download")
        self._stage(job, "thumbnail", 0.14)
        thumbnail = await self._thread_call(client.cache_thumbnail, extracted, folder)
        if thumbnail:
            self._log(job, f"[TRANSCRIPT] Thumbnail saved: {thumbnail.name}")
            meta.thumbnail_file = thumbnail.name
            self.storage.save_meta(meta, folder)
            self._event(
                job, "thumbnail", f"Preview saved: {thumbnail.name}", "completed"
            )
        else:
            self._log(job, "[TRANSCRIPT] Thumbnail unavailable")
            self._event(
                job,
                "thumbnail",
                "Preview unavailable; continuing without local thumbnail",
                "progress",
            )
        self._complete_stage(job, "thumbnail", 0.18, "Thumbnail branch completed")

        await self._wait_until_resumed()
        self._log(job, "[TRANSCRIPT] Selecting original transcript")
        self._stage(job, "transcript-selection", 0.22)
        original_choice = client.choose_original_transcript(extracted)
        self._log(
            job,
            f"[TRANSCRIPT] Original transcript choice: {original_choice.language if original_choice else 'None (will use ASR fallback)'}",
        )
        self._complete_stage(
            job, "transcript-selection", 0.24, "Transcript candidates selected"
        )
        if original_choice:
            self._log(
                job,
                f"[TRANSCRIPT] Downloading caption transcript: language={original_choice.language}",
            )
            original = await self._save_caption_transcript(
                job,
                client,
                extracted,
                original_choice,
                "original",
                meta,
                folder,
                work_dir,
            )
        else:
            self._log(
                job,
                "[TRANSCRIPT] No usable YouTube transcript; switching to local audio transcription (ASR fallback)",
            )
            await self._wait_until_resumed()
            async with self.resources.stage(
                job,
                "audio-download",
                "yt_dlp",
                progress=0.30,
                message="Downloading audio fallback",
            ):
                self._log(
                    job,
                    f"[TRANSCRIPT_ASR] Starting audio download to fallback path: {work_dir}",
                )
                audio_path = await self._thread_call(
                    client.download_audio, extracted, work_dir
                )
                self._log(
                    job, f"[TRANSCRIPT_ASR] Audio download completed: {audio_path}"
                )
                self._log(
                    job,
                    f"[TRANSCRIPT_ASR] Audio file details: exists={audio_path.exists()}, size={audio_path.stat().st_size if audio_path.exists() else 'N/A'} bytes, readable={audio_path.is_file() if audio_path.exists() else False}",
                )
            self._check_cancelled(job)
            await self._wait_until_resumed()
            self._log(
                job,
                f"[TRANSCRIPT_ASR] Initializing Meeting Transcriber with engine={settings.asr_engine}",
            )
            async with self.resources.stage(
                job,
                "transcribing",
                "asr",
                progress=0.50,
                message="Transcribing audio with Meeting Transcriber",
            ):
                self._log(
                    job,
                    f"[TRANSCRIPT_ASR] Sending audio to Meeting Transcriber: {audio_path}",
                )
                segments = await MeetingTranscriberBridge(settings).transcribe(
                    audio_path
                )
                self._log(
                    job,
                    f"[TRANSCRIPT_ASR] Meeting Transcriber returned {len(segments)} segments",
                )
            self._log(
                job,
                f"[TRANSCRIPT_ASR] Transcribed {len(segments)} segments, language will be {settings.asr_language or extracted.original_language or 'auto'}",
            )
            self._stage(job, "transcript-normalize", 0.60)
            original = self._write_transcript(
                meta,
                folder,
                "original",
                settings.asr_language or extracted.original_language or "auto",
                "local_asr",
                "local_asr",
                settings.asr_engine,
                segments,
            )
            self._log(job, f"[TRANSCRIPT_ASR] ASR transcript written: {original.file}")
            self._complete_stage(
                job, "transcript-normalize", 0.64, "ASR transcript normalized"
            )
            if settings.keep_audio:
                self._log(job, "[TRANSCRIPT_ASR] Keeping audio file per settings")
                shutil.copy2(audio_path, folder / "audio.wav")

        if not original:
            raise RuntimeError("Transcript is empty")
        self._log(
            job,
            f"[TRANSCRIPT] Primary transcript set: {original.language}/{original.kind}/{original.source}",
        )
        meta.transcript = original
        settings_choice = client.choose_transcript(extracted)
        if settings_choice and settings_choice.language != original.language:
            self._log(
                job,
                f"[TRANSCRIPT] Downloading alternate language transcript: {settings_choice.language}",
            )
            localized = await self._save_caption_transcript(
                job,
                client,
                extracted,
                settings_choice,
                "settings",
                meta,
                folder,
                work_dir,
            )
            if localized:
                self._log(
                    job,
                    f"[TRANSCRIPT] Settings-language transcript saved: {localized.language}/{localized.kind}",
                )
        elif settings_choice:
            self._log(
                job,
                f"[TRANSCRIPT] Settings-language transcript matches the original ({settings_choice.language}); no duplicate file created",
            )
        meta.status = "transcript_ready"
        meta.error = None
        self.storage.save_meta(meta, folder)
        self.storage.update_search(meta.video_id)
        self._log(job, "[TRANSCRIPT] Transcript preparation complete")
        self._stage(job, "transcript-ready", 0.68)
        self._complete_stage(
            job, "transcript-ready", 1, "Transcript artifact committed"
        )

    def _write_transcript(
        self,
        meta: VideoMeta,
        folder: Path,
        role: str,
        language: str,
        kind: str,
        source: str,
        engine: str | None,
        segments: list,
    ) -> TranscriptInfo:
        if not segments:
            raise RuntimeError("Transcript is empty")
        info = TranscriptInfo(
            file=transcript_filename(role, language, kind, utc_now()),
            language=language,
            kind=kind,
            source=source,
            role=role,
            engine=engine,
            segment_count=len(segments),
        )
        markdown = transcript_markdown(
            video_id=meta.video_id,
            title=meta.title,
            language=language,
            kind=kind,
            engine=engine,
            segments=segments,
        )
        path = folder / info.file
        suffix = 2
        while path.exists():
            info.file = info.file.removesuffix(".md") + f"-{suffix}.md"
            path = folder / info.file
            suffix += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, markdown)
        meta.transcripts.append(info)
        return info

    async def _save_caption_transcript(
        self,
        job: JobRecord,
        client: YouTubeClient,
        extracted,
        choice: SubtitleChoice,
        role: str,
        meta: VideoMeta,
        folder: Path,
        work_dir: Path,
    ) -> TranscriptInfo:
        self._log(
            job, f"Selected {role} {choice.kind} transcript language {choice.language}"
        )
        stage = f"subtitle-download:{role}:{choice.language}"
        await self._wait_until_resumed()
        async with self.resources.stage(
            job,
            stage,
            "yt_dlp",
            progress=0.32,
            message=f"Downloading {role} {choice.language} transcript",
        ):
            caption_file = await self._thread_call(
                client.download_subtitle, extracted, choice, work_dir / role
            )
        raw_dir = folder / "transcripts" / "source"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_name = f"{safe_component(role)}-{safe_component(choice.language)}-{safe_component(choice.kind)}-{safe_component(utc_now())}{caption_file.suffix}"
        raw_path = raw_dir / raw_name
        suffix = 2
        while raw_path.exists():
            raw_path = raw_dir / f"{Path(raw_name).stem}-{suffix}{caption_file.suffix}"
            suffix += 1
        temporary_raw = raw_path.with_suffix(raw_path.suffix + ".tmp")
        shutil.copyfile(caption_file, temporary_raw)
        temporary_raw.replace(raw_path)
        self._stage(job, "transcript-normalize", 0.58)
        info = self._write_transcript(
            meta,
            folder,
            role,
            choice.language,
            choice.kind,
            "youtube",
            None,
            parse_caption_file(caption_file),
        )
        info.raw_file = str(raw_path.relative_to(folder))
        self._complete_stage(
            job, "transcript-normalize", 0.62, f"{role} transcript normalized"
        )
        self._log(
            job,
            f"Transcript written: {info.file} ({info.language}/{info.kind}/{info.source})",
        )
        return info

    async def _create_summary(self, job: JobRecord, settings: AppSettings) -> None:
        self._log(job, "[SUMMARY] Starting summary creation")
        detail = self.storage.get_video(job.video_id)
        if not detail or not detail.folder or not detail.transcript_markdown:
            raise RuntimeError("Transcript is not ready")
        self._log(
            job,
            f"[SUMMARY] Transcript ready: length={len(detail.transcript_markdown)} chars",
        )
        overrides = job.overrides
        self._log(job, f"[SUMMARY] Processing overrides: {overrides}")
        provider_id = overrides.get("provider_id") or settings.active_provider_id
        self._log(job, f"[SUMMARY] Selected provider_id: {provider_id}")
        primary_provider = next(
            (item for item in settings.providers if item.id == provider_id), None
        )
        if not primary_provider:
            raise RuntimeError(f"Summary provider '{provider_id}' not found")
        if not primary_provider.enabled:
            raise RuntimeError(f"Summary provider '{provider_id}' is disabled")
        if overrides.get("model"):
            self._log(job, f"[SUMMARY] Overriding model to {overrides['model']}")
            primary_provider = primary_provider.model_copy(
                update={"model": overrides["model"]}
            )
        if not primary_provider.model:
            raise RuntimeError("Choose a summary model in Settings")
        providers = [primary_provider]
        if (
            settings.parallel_summary_sources
            and not overrides.get("provider_id")
            and not overrides.get("model")
        ):
            self._log(job, "[SUMMARY] Parallel summaries enabled, using all providers")
            providers = [
                item for item in settings.providers if item.enabled and item.model
            ]
        self._log(job, f"[SUMMARY] Providers selected: {len(providers)} providers")
        if not providers:
            raise RuntimeError("Enable at least one configured summary source")
        template_id = overrides.get("template_id") or settings.summary_template_id
        template = next(
            (item for item in settings.templates if item.id == template_id), None
        )
        if not template:
            raise RuntimeError(f"Summary template '{template_id}' not found")
        self._log(job, f"[SUMMARY] Template selected: {template.id}")
        language = overrides.get("language") or settings.summary_language
        mode = overrides.get("mode") or settings.summary_mode
        self._log(job, f"[SUMMARY] Language={language}, Mode={mode}")
        self._stage(job, "summarizing", 0.72)
        source_label = ", ".join(f"{item.name}/{item.model}" for item in providers)
        job.summary_source = "transcript.md"
        job.provider_id = ", ".join(item.id for item in providers)
        job.provider_name = ", ".join(item.name for item in providers)
        job.model = ", ".join(item.model for item in providers)
        self.storage.update_job(
            job.id,
            summary_source=job.summary_source,
            provider_id=job.provider_id,
            provider_name=job.provider_name,
            model=job.model,
        )
        self._event(
            job,
            "summary-source",
            f"Source: {job.summary_source}; provider/model: {source_label}",
            "started",
        )
        self._log(job, f"[SUMMARY] Starting summary across {source_label} ({mode})")

        def report(progress: SummaryProgress) -> None:
            job.stage = progress.stage
            job.requests_planned = progress.requests_planned
            job.requests_completed = progress.requests_completed
            if progress.provider_id:
                job.provider_id = progress.provider_id
                job.provider_name = progress.provider_name
                job.model = progress.model
            job.progress = min(
                0.97,
                0.72
                + 0.25
                * (progress.requests_completed / max(1, progress.requests_planned)),
            )
            self.storage.update_job(
                job.id,
                stage=job.stage,
                progress=job.progress,
                requests_planned=job.requests_planned,
                requests_completed=job.requests_completed,
                provider_id=job.provider_id,
                provider_name=job.provider_name,
                model=job.model,
            )
            transition = {
                "started": "running",
                "progress": "running",
                "completed": "succeeded",
                "failed": "failed",
            }[progress.status]
            stage_task = (
                f"{progress.stage}:{progress.operation_id}"
                if progress.operation_id
                else progress.stage
            )
            self.storage.transition_stage(
                job.id,
                stage_task,
                transition,
                progress=job.progress,
                message=progress.message,
                error=progress.message if transition == "failed" else None,
            )
            self._event(job, progress.stage, progress.message, progress.status)

        self._log(
            job, f"[SUMMARY] Running Summarizer with {len(providers)} provider(s)"
        )
        result = await Summarizer(
            settings, providers, template, pause_waiter=self._wait_until_resumed
        ).run(
            detail.transcript_markdown,
            language=language,
            model=primary_provider.model,
            mode=mode,
            on_progress=report,
        )
        self._log(
            job,
            f"[SUMMARY] Summarizer completed: {result.request_count} request(s), output_length={len(result.markdown)} chars",
        )
        folder = Path(detail.folder)
        history_dir = folder / "summary-history"
        history_dir.mkdir(exist_ok=True)
        if (folder / "summary.md").exists() and detail.meta.current_summary:
            self._log(job, "[SUMMARY] Previous summary exists, archiving to history")
            previous = detail.meta.current_summary
            history_name = f"{safe_component(previous.generated_at)}-{safe_component(previous.model)}-{safe_component(previous.template_id)}.md"
            shutil.copy2(folder / "summary.md", history_dir / history_name)
            previous.file = f"summary-history/{history_name}"
            detail.meta.summary_versions.append(previous)
        self._log(job, "[SUMMARY] Writing summary to disk")
        atomic_write(folder / "summary.md", result.markdown)
        detail.meta.current_summary = SummaryVersion(
            file="summary.md",
            provider_id=", ".join(result.provider_ids),
            model=", ".join(result.models),
            template_id=template.id,
            language=language,
            mode=mode,
        )
        detail.meta.summary_stale = False
        detail.meta.status = "complete"
        detail.meta.error = None
        self.storage.save_meta(detail.meta, folder)
        self.storage.update_search(job.video_id)
        self._log(
            job,
            f"[SUMMARY] Summary created across {source_label} in {result.request_count} request(s)",
        )
        self._complete_stage(job, "summarizing", 1, "Summary artifact committed")

    async def _create_prompt_artifact(
        self, job: JobRecord, settings: AppSettings
    ) -> None:
        """Run one reusable prompt without replacing the canonical summary."""
        self._log(job, "[PROMPT] Starting prompt artifact creation")
        detail = self.storage.get_video(job.video_id)
        if not detail or not detail.folder or not detail.transcript_markdown:
            raise RuntimeError("Transcript is not ready")
        template_id = job.overrides.get("template_id")
        self._log(job, f"[PROMPT] Template ID from overrides: {template_id}")
        template = next(
            (item for item in settings.templates if item.id == template_id), None
        )
        if not template:
            raise RuntimeError(f"Prompt template '{template_id}' not found")
        provider_id = job.overrides.get("provider_id") or settings.active_provider_id
        self._log(job, f"[PROMPT] Provider ID: {provider_id}")
        provider = next(
            (item for item in settings.providers if item.id == provider_id), None
        )
        if not provider:
            raise RuntimeError(f"Summary provider '{provider_id}' not found")
        if not provider.enabled:
            raise RuntimeError(f"Summary provider '{provider_id}' is disabled")
        if job.overrides.get("model"):
            self._log(job, f"[PROMPT] Overriding model to {job.overrides['model']}")
            provider = provider.model_copy(update={"model": job.overrides["model"]})
        if not provider.model:
            raise RuntimeError("Choose a summary model in Settings")
        language = job.overrides.get("language") or settings.summary_language
        self._log(job, f"[PROMPT] Language: {language}")
        self._stage(job, "running-prompt", 0.72)
        self._log(
            job,
            f"[PROMPT] Running prompt '{template.id}' with {provider.name}/{provider.model}",
        )

        def report(progress: SummaryProgress) -> None:
            job.stage = progress.stage
            job.requests_planned = progress.requests_planned
            job.requests_completed = progress.requests_completed
            job.progress = min(
                0.97,
                0.72
                + 0.25
                * (progress.requests_completed / max(1, progress.requests_planned)),
            )
            self.storage.update_job(
                job.id,
                stage=job.stage,
                progress=job.progress,
                requests_planned=job.requests_planned,
                requests_completed=job.requests_completed,
            )
            transition = {
                "started": "running",
                "progress": "running",
                "completed": "succeeded",
                "failed": "failed",
            }[progress.status]
            stage_task = (
                f"{progress.stage}:{progress.operation_id}"
                if progress.operation_id
                else progress.stage
            )
            self.storage.transition_stage(
                job.id,
                stage_task,
                transition,
                progress=job.progress,
                message=progress.message,
                error=progress.message if transition == "failed" else None,
            )
            self._event(job, progress.stage, progress.message, progress.status)

        self._log(job, "[PROMPT] Running Summarizer with prompt template")
        result = await Summarizer(
            settings, [provider], template, pause_waiter=self._wait_until_resumed
        ).run(
            detail.transcript_markdown,
            language=language,
            model=provider.model,
            mode="cluster",
            on_progress=report,
        )
        self._log(
            job,
            f"[PROMPT] Summarizer completed: output_length={len(result.markdown)} chars",
        )
        folder = Path(detail.folder)
        relative_file = (
            f"artifacts/{safe_component(template.id)}-{safe_component(job.id)}.md"
        )
        artifact_path = folder / relative_file
        artifact_path.parent.mkdir(exist_ok=True)
        self._log(job, f"[PROMPT] Writing artifact to {relative_file}")
        atomic_write(artifact_path, result.markdown)
        detail.meta.prompt_artifacts.insert(
            0,
            PromptArtifact(
                id=job.id,
                file=relative_file,
                template_id=template.id,
                template_name=template.name_ru,
                provider_id=", ".join(result.provider_ids),
                model=", ".join(result.models),
                language=language,
            ),
        )
        detail.meta.error = None
        self.storage.save_meta(detail.meta, folder)
        self.storage.update_search(job.video_id)
        self._log(job, f"[PROMPT] Prompt artifact written: {relative_file}")
        self._complete_stage(job, "running-prompt", 1, "Prompt artifact committed")

    async def _create_speech(self, job: JobRecord, settings: AppSettings) -> None:
        self._log(job, "[TTS] Starting speech synthesis")
        detail = self.storage.get_video(job.video_id)
        if not detail or not detail.folder:
            raise RuntimeError("Video folder is not ready")
        artifact = job.overrides.get("artifact")
        self._log(job, f"[TTS] Artifact type: {artifact}")
        if artifact not in {"transcript", "summary"}:
            raise RuntimeError("Choose a transcript or summary to narrate")
        source = (
            detail.transcript_markdown
            if artifact == "transcript"
            else detail.summary_markdown
        )
        self._log(job, f"[TTS] Source length: {len(source)} chars")
        speech = markdown_to_speech(source)
        if not speech:
            raise RuntimeError(f"{artifact.capitalize()} is not ready")
        self._log(job, f"[TTS] Speech text prepared: {len(speech)} chars")
        self._log(
            job,
            f"[TTS] TTS engine: {settings.tts_engine}, voice: {settings.tts_voice or 'system default'}",
        )
        filename = f"{artifact}-speech.m4a"
        output = Path(detail.folder) / filename
        await self._wait_until_resumed()
        self._log(job, f"[TTS] Starting synthesis, output: {filename}")
        async with self.resources.stage(
            job,
            "speech-synthesis",
            "tts",
            progress=0.25,
            message=f"Synthesizing {artifact}",
        ):
            await self._thread_call(MacSayTTS(settings).synthesize, speech, output)
        self._log(job, "[TTS] Synthesis completed")
        self._check_cancelled(job)
        self._stage(job, "saving-audio", 0.9)
        detail.meta.audio_artifacts = [
            item for item in detail.meta.audio_artifacts if item.artifact != artifact
        ]
        detail.meta.audio_artifacts.append(
            AudioArtifact(
                file=filename,
                artifact=artifact,
                engine=settings.tts_engine,
                voice=settings.tts_voice or "system",
                rate=settings.tts_rate,
            )
        )
        self.storage.save_meta(detail.meta, Path(detail.folder))
        self._log(job, f"[TTS] Speech saved: {filename}")
        self._complete_stage(job, "saving-audio", 1, "Audio artifact committed")
