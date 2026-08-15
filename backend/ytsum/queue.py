from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Callable

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
                self._task = asyncio.create_task(asyncio.sleep(3600), name="yt-sum-test-worker")
                return
            self._download_tasks = [
                asyncio.create_task(self._run_downloads(index), name=f"yt-sum-download-worker-{index + 1}")
                for index in range(2)
            ]
            self._task = self._download_tasks[0]
            settings = self.settings_repo.load()
            worker_count = max(1, len([provider for provider in settings.providers if provider.enabled and provider.model]))
            self._llm_target = worker_count
            self._llm_tasks = [
                asyncio.create_task(self._run_llm(index), name=f"yt-sum-llm-worker-{index + 1}")
                for index in range(worker_count)
            ]
            self._tts_tasks = [asyncio.create_task(self._run_tts(), name="yt-sum-tts-worker")]

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
                self._log(active_job, "Paused for application shutdown; will resume after restart")
            tasks = [task for task in [*self._download_tasks, *self._llm_tasks, *self._tts_tasks, self._resize_task] if task]
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
            self._resize_task = loop.create_task(self._sync_llm_workers(), name="yt-sum-llm-pool-sync")

    async def _sync_llm_workers(self) -> None:
        try:
            if not self.settings_repo or self._stopping:
                return
            target = max(1, len([provider for provider in self.settings_repo.load().providers if provider.enabled and provider.model]))
            self._llm_target = target
            self._llm_tasks = [task for task in self._llm_tasks if not task.done()]
            while len(self._llm_tasks) < target and not self._stopping:
                index = len(self._llm_tasks)
                self._llm_tasks.append(asyncio.create_task(self._run_llm(index), name=f"yt-sum-llm-worker-{index + 1}"))
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
        jobs = [job for job in self.storage.list_jobs() if job.status in {"queued", "processing"}]
        for job in jobs:
            self.cancel(job.id)
        self.notify()
        return len(jobs)

    async def _run_lane(self, kinds: tuple[str, ...], worker_name: str, should_continue=lambda: True) -> None:
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
                await self._execute(job)
            except asyncio.CancelledError:
                if self._stopping:
                    raise
                self.storage.update_job(job.id, status="cancelled", execution_state="cancelled", error="Cancelled by user")
                self.storage.finish_workflow(job.id, "cancelled")
                self._log(job, "Cancelled by user")
                self._event(job, "cancelled", "Cancelled by user", "failed")
            finally:
                self._job_tasks.pop(job.id, None)
                self._active_jobs.pop(worker_name, None)

    async def _run_downloads(self, index: int) -> None:
        await self._run_lane(self.DOWNLOAD_KINDS, f"downloads-{index}")

    async def _run_llm(self, index: int) -> None:
        await self._run_lane(self.LLM_KINDS, f"llm-{index}", lambda: index < self._llm_target)

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

    def _event(self, job: JobRecord, stage: str, message: str, status: str = "progress", **changes: object) -> None:
        """Persist a structured, safe checkpoint for both API clients and the UI."""
        message = re.sub(r"(?i)(authorization|api[_ -]?key|bearer)\s*[:=]\s*\S+", r"\1: [redacted]", message)
        event = JobStageEvent(
            stage=stage,
            message=message,
            status=status,  # type: ignore[arg-type]
            requests_planned=job.requests_planned,
            requests_completed=job.requests_completed,
        )
        job.stage_log.append(event)
        self.storage.update_job(job.id, stage_log_json=[item.model_dump(mode="json") for item in job.stage_log], **changes)

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

    def _complete_stage(self, job: JobRecord, stage: str, progress: float, message: str) -> None:
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
        workflow = self.storage.get_workflow(job.workflow_id) if job.workflow_id else None
        settings = (
            AppSettings.model_validate(workflow.settings_snapshot)
            if workflow and workflow.settings_snapshot
            else self.settings_repo.load()
        )
        work_dir = self.storage.work_dir / job.id
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._event(job, "starting", f"Starting {job.kind} job", "started")
            self._log(job, f"Starting {job.kind} job for {job.video_id}")
            acquisition_job = job.kind in {"process", "refresh"}
            if acquisition_job:
                await self._prepare_transcript(job, settings, work_dir)
            self._check_cancelled(job)
            if acquisition_job:
                self.storage.update_job(
                    job.id,
                    status="complete",
                    stage="transcript-ready",
                    execution_state="succeeded",
                    progress=1,
                    error=None,
                )
                self._log(job, "Transcript workflow completed; summary queued independently")
                self.storage.enqueue(
                    job.video_id,
                    job.source_url,
                    kind="summarize",
                    workflow_id=job.workflow_id,
                )
                self.notify()
                return
            if job.kind == "tts":
                await self._create_speech(job, settings)
            elif job.kind == "prompt":
                await self._create_prompt_artifact(job, settings)
            else:
                await self._create_summary(job, settings)
            self.storage.update_job(
                job.id, status="complete", stage=job.stage, execution_state="succeeded", progress=1, error=None
            )
            self.storage.finish_workflow(job.id, "complete")
            self._log(job, "Job completed")
            self._event(job, "complete", "Job completed", "completed")
        except JobCancelled as error:
            self.storage.update_job(
                job.id, status="cancelled", execution_state="cancelled", error=str(error)
            )
            self.storage.finish_workflow(job.id, "cancelled")
            self._log(job, str(error))
            self._event(job, "cancelled", str(error), "failed")
        except Exception as error:
            parent_stage = {"summarize": "summarizing", "prompt": "running-prompt"}.get(job.kind)
            if parent_stage:
                self.storage.transition_stage(
                    job.id,
                    parent_stage,
                    "failed",
                    progress=job.progress,
                    message=str(error),
                    error=str(error),
                )
            self.storage.update_job(
                job.id,
                status="attention",
                execution_state="failed",
                error=str(error),
                attempts=job.attempts + 1,
            )
            self.storage.finish_workflow(job.id, "attention")
            detail = self.storage.get_video(job.video_id)
            if detail and detail.folder:
                detail.meta.status = "partially_ready" if detail.transcript_markdown.strip() else "attention"
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
        checkpoint = self.storage.get_video(job.video_id)
        if job.kind == "process" and checkpoint and checkpoint.transcript_markdown.strip():
            self._log(job, "Verified transcript checkpoint found; YouTube acquisition skipped")
            self.storage.transition_stage(
                job.id,
                "transcript-ready",
                "succeeded",
                progress=1,
                message="Existing transcript checkpoint verified",
            )
            return
        client = YouTubeClient(settings)
        await self._wait_until_resumed()
        async with self.resources.stage(
            job,
            "metadata",
            "yt_dlp",
            progress=0.08,
            message="Fetching metadata and transcript inventory",
        ):
            self._event(job, "metadata", f"Fetching metadata from {job.source_url}", "progress")
            extracted = await self._thread_call(client.extract, job.source_url)
        languages = ", ".join(extracted.available_languages) if extracted.available_languages else "none reported"
        duration = f"{extracted.duration_seconds}s" if extracted.duration_seconds is not None else "unknown duration"
        self._log(job, f"Metadata extracted: title={extracted.title!r}; channel={extracted.channel or 'unknown'}; duration={duration}; languages={languages}")
        self._event(job, "metadata", f"Metadata received: {extracted.title} · {extracted.channel or 'unknown channel'} · {duration}", "completed")
        self._event(job, "metadata", f"Subtitle languages reported: {languages}", "progress")
        self._check_cancelled(job)
        previous = self.storage.read_meta(job.video_id)
        existing = self.storage.get_video(job.video_id)
        previous_meta = previous[0] if previous else (existing.meta if existing else None)
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
        folder = self.storage.create_video_folder(meta)
        self.storage.save_meta(meta, folder)

        await self._wait_until_resumed()
        self._stage(job, "thumbnail", 0.14)
        thumbnail = await self._thread_call(client.cache_thumbnail, extracted, folder)
        if thumbnail:
            meta.thumbnail_file = thumbnail.name
            self.storage.save_meta(meta, folder)
            self._event(job, "thumbnail", f"Preview saved: {thumbnail.name}", "completed")
        else:
            self._event(job, "thumbnail", "Preview unavailable; continuing without local thumbnail", "progress")
        self._complete_stage(job, "thumbnail", 0.18, "Thumbnail branch completed")

        await self._wait_until_resumed()
        self._stage(job, "transcript-selection", 0.22)
        original_choice = client.choose_original_transcript(extracted)
        self._complete_stage(job, "transcript-selection", 0.24, "Transcript candidates selected")
        if original_choice:
            original = await self._save_caption_transcript(job, client, extracted, original_choice, "original", meta, folder, work_dir)
        else:
            self._log(
                job,
                "No usable YouTube transcript; switching to local audio transcription",
            )
            await self._wait_until_resumed()
            async with self.resources.stage(
                job,
                "audio-download",
                "yt_dlp",
                progress=0.30,
                message="Downloading audio fallback",
            ):
                audio_path = await self._thread_call(client.download_audio, extracted, work_dir)
            self._check_cancelled(job)
            await self._wait_until_resumed()
            async with self.resources.stage(
                job,
                "transcribing",
                "asr",
                progress=0.50,
                message="Transcribing audio with Meeting Transcriber",
            ):
                segments = await MeetingTranscriberBridge(settings).transcribe(audio_path)
            self._log(job, f"Transcribed {len(segments)} segments")
            self._stage(job, "transcript-normalize", 0.60)
            original = self._write_transcript(meta, folder, "original", settings.asr_language or extracted.original_language or "auto", "local_asr", "local_asr", settings.asr_engine, segments)
            self._complete_stage(job, "transcript-normalize", 0.64, "ASR transcript normalized")
            if settings.keep_audio:
                shutil.copy2(audio_path, folder / "audio.wav")

        if not original:
            raise RuntimeError("Transcript is empty")
        meta.transcript = original
        settings_choice = client.choose_transcript(extracted)
        if settings_choice and settings_choice.language != original.language:
            localized = await self._save_caption_transcript(job, client, extracted, settings_choice, "settings", meta, folder, work_dir)
            if localized:
                self._log(job, f"Settings-language transcript saved: {localized.language}/{localized.kind}")
        elif settings_choice:
            self._log(job, "Settings-language transcript matches the original; no duplicate file created")
        meta.status = "transcript_ready"
        meta.error = None
        self.storage.save_meta(meta, folder)
        self.storage.update_search(meta.video_id)
        self._stage(job, "transcript-ready", 0.68)
        self._complete_stage(job, "transcript-ready", 1, "Transcript artifact committed")

    def _write_transcript(self, meta: VideoMeta, folder: Path, role: str, language: str, kind: str, source: str, engine: str | None, segments: list) -> TranscriptInfo:
        if not segments:
            raise RuntimeError("Transcript is empty")
        info = TranscriptInfo(file=transcript_filename(role, language, kind, utc_now()), language=language, kind=kind, source=source, role=role, engine=engine, segment_count=len(segments))
        markdown = transcript_markdown(video_id=meta.video_id, title=meta.title, language=language, kind=kind, engine=engine, segments=segments)
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

    async def _save_caption_transcript(self, job: JobRecord, client: YouTubeClient, extracted, choice: SubtitleChoice, role: str, meta: VideoMeta, folder: Path, work_dir: Path) -> TranscriptInfo:
        self._log(job, f"Selected {role} {choice.kind} transcript language {choice.language}")
        stage = f"subtitle-download:{role}:{choice.language}"
        await self._wait_until_resumed()
        async with self.resources.stage(
            job,
            stage,
            "yt_dlp",
            progress=0.32,
            message=f"Downloading {role} {choice.language} transcript",
        ):
            caption_file = await self._thread_call(client.download_subtitle, extracted, choice, work_dir / role)
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
        info = self._write_transcript(meta, folder, role, choice.language, choice.kind, "youtube", None, parse_caption_file(caption_file))
        info.raw_file = str(raw_path.relative_to(folder))
        self._complete_stage(job, "transcript-normalize", 0.62, f"{role} transcript normalized")
        self._log(job, f"Transcript written: {info.file} ({info.language}/{info.kind}/{info.source})")
        return info

    async def _create_summary(self, job: JobRecord, settings: AppSettings) -> None:
        detail = self.storage.get_video(job.video_id)
        if not detail or not detail.folder or not detail.transcript_markdown:
            raise RuntimeError("Transcript is not ready")
        overrides = job.overrides
        provider_id = overrides.get("provider_id") or settings.active_provider_id
        primary_provider = next(
            (item for item in settings.providers if item.id == provider_id), None
        )
        if not primary_provider:
            raise RuntimeError(f"Summary provider '{provider_id}' not found")
        if overrides.get("model"):
            primary_provider = primary_provider.model_copy(update={"model": overrides["model"]})
        if not primary_provider.model:
            raise RuntimeError("Choose a summary model in Settings")
        providers = [primary_provider]
        if settings.parallel_summary_sources and not overrides.get("provider_id") and not overrides.get("model"):
            providers = [item for item in settings.providers if item.enabled and item.model]
        if not providers:
            raise RuntimeError("Enable at least one configured summary source")
        template_id = overrides.get("template_id") or settings.summary_template_id
        template = next(
            (item for item in settings.templates if item.id == template_id), None
        )
        if not template:
            raise RuntimeError(f"Summary template '{template_id}' not found")
        language = overrides.get("language") or settings.summary_language
        mode = overrides.get("mode") or settings.summary_mode
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
        self._event(job, "summary-source", f"Source: {job.summary_source}; provider/model: {source_label}", "started")
        self._log(job, f"Starting summary across {source_label} ({mode})")

        def report(progress: SummaryProgress) -> None:
            job.stage = progress.stage
            job.requests_planned = progress.requests_planned
            job.requests_completed = progress.requests_completed
            if progress.provider_id:
                job.provider_id = progress.provider_id
                job.provider_name = progress.provider_name
                job.model = progress.model
            job.progress = min(0.97, 0.72 + 0.25 * (progress.requests_completed / max(1, progress.requests_planned)))
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
            stage_task = f"{progress.stage}:{progress.operation_id}" if progress.operation_id else progress.stage
            self.storage.transition_stage(
                job.id,
                stage_task,
                transition,
                progress=job.progress,
                message=progress.message,
                error=progress.message if transition == "failed" else None,
            )
            self._event(job, progress.stage, progress.message, progress.status)

        result = await Summarizer(settings, providers, template, pause_waiter=self._wait_until_resumed).run(
            detail.transcript_markdown, language=language, model=primary_provider.model, mode=mode, on_progress=report
        )
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
            f"Summary created across {source_label} in {result.request_count} request(s)",
        )
        self._complete_stage(job, "summarizing", 1, "Summary artifact committed")

    async def _create_prompt_artifact(self, job: JobRecord, settings: AppSettings) -> None:
        """Run one reusable prompt without replacing the canonical summary."""
        detail = self.storage.get_video(job.video_id)
        if not detail or not detail.folder or not detail.transcript_markdown:
            raise RuntimeError("Transcript is not ready")
        template_id = job.overrides.get("template_id")
        template = next((item for item in settings.templates if item.id == template_id), None)
        if not template:
            raise RuntimeError(f"Prompt template '{template_id}' not found")
        provider_id = job.overrides.get("provider_id") or settings.active_provider_id
        provider = next((item for item in settings.providers if item.id == provider_id), None)
        if not provider:
            raise RuntimeError(f"Summary provider '{provider_id}' not found")
        if job.overrides.get("model"):
            provider = provider.model_copy(update={"model": job.overrides["model"]})
        if not provider.model:
            raise RuntimeError("Choose a summary model in Settings")
        language = job.overrides.get("language") or settings.summary_language
        self._stage(job, "running-prompt", 0.72)
        self._log(job, f"Running prompt '{template.id}' with {provider.name}/{provider.model}")

        def report(progress: SummaryProgress) -> None:
            job.stage = progress.stage
            job.requests_planned = progress.requests_planned
            job.requests_completed = progress.requests_completed
            job.progress = min(0.97, 0.72 + 0.25 * (progress.requests_completed / max(1, progress.requests_planned)))
            self.storage.update_job(job.id, stage=job.stage, progress=job.progress, requests_planned=job.requests_planned, requests_completed=job.requests_completed)
            transition = {
                "started": "running",
                "progress": "running",
                "completed": "succeeded",
                "failed": "failed",
            }[progress.status]
            stage_task = f"{progress.stage}:{progress.operation_id}" if progress.operation_id else progress.stage
            self.storage.transition_stage(
                job.id,
                stage_task,
                transition,
                progress=job.progress,
                message=progress.message,
                error=progress.message if transition == "failed" else None,
            )
            self._event(job, progress.stage, progress.message, progress.status)

        result = await Summarizer(settings, [provider], template, pause_waiter=self._wait_until_resumed).run(
            detail.transcript_markdown, language=language, model=provider.model, mode="cluster", on_progress=report
        )
        folder = Path(detail.folder)
        relative_file = f"artifacts/{safe_component(template.id)}-{safe_component(job.id)}.md"
        artifact_path = folder / relative_file
        artifact_path.parent.mkdir(exist_ok=True)
        atomic_write(artifact_path, result.markdown)
        detail.meta.prompt_artifacts.insert(0, PromptArtifact(
            id=job.id, file=relative_file, template_id=template.id,
            template_name=template.name_ru, provider_id=", ".join(result.provider_ids),
            model=", ".join(result.models), language=language,
        ))
        detail.meta.error = None
        self.storage.save_meta(detail.meta, folder)
        self.storage.update_search(job.video_id)
        self._log(job, f"Prompt artifact written: {relative_file}")
        self._complete_stage(job, "running-prompt", 1, "Prompt artifact committed")

    async def _create_speech(self, job: JobRecord, settings: AppSettings) -> None:
        detail = self.storage.get_video(job.video_id)
        if not detail or not detail.folder:
            raise RuntimeError("Video folder is not ready")
        artifact = job.overrides.get("artifact")
        if artifact not in {"transcript", "summary"}:
            raise RuntimeError("Choose a transcript or summary to narrate")
        source = detail.transcript_markdown if artifact == "transcript" else detail.summary_markdown
        speech = markdown_to_speech(source)
        if not speech:
            raise RuntimeError(f"{artifact.capitalize()} is not ready")
        self._log(job, f"Synthesizing {artifact} with {settings.tts_engine}/{settings.tts_voice or 'system default'}")
        filename = f"{artifact}-speech.m4a"
        output = Path(detail.folder) / filename
        await self._wait_until_resumed()
        async with self.resources.stage(
            job,
            "speech-synthesis",
            "tts",
            progress=0.25,
            message=f"Synthesizing {artifact}",
        ):
            await self._thread_call(MacSayTTS(settings).synthesize, speech, output)
        self._check_cancelled(job)
        self._stage(job, "saving-audio", 0.9)
        detail.meta.audio_artifacts = [item for item in detail.meta.audio_artifacts if item.artifact != artifact]
        detail.meta.audio_artifacts.append(AudioArtifact(file=filename, artifact=artifact, engine=settings.tts_engine, voice=settings.tts_voice or "system", rate=settings.tts_rate))
        self.storage.save_meta(detail.meta, Path(detail.folder))
        self._log(job, f"Speech saved: {filename}")
        self._complete_stage(job, "saving-audio", 1, "Audio artifact committed")
