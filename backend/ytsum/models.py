from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    speaker: str | None = None


class TranscriptInfo(BaseModel):
    file: str = ""
    raw_file: str | None = None
    language: str
    kind: Literal["author", "automatic", "original", "local_asr"]
    source: Literal["youtube", "local_asr"] = "youtube"
    role: Literal["original", "settings"] = "original"
    engine: str | None = None
    segment_count: int = 0
    generated_at: str = Field(default_factory=utc_now)


class SummaryVersion(BaseModel):
    file: str
    provider_id: str
    model: str
    template_id: str
    language: str
    mode: Literal["complete", "cluster"] = "complete"
    generated_at: str = Field(default_factory=utc_now)


class PromptArtifact(BaseModel):
    """An independently generated result kept alongside a video's transcript."""

    id: str
    file: str
    template_id: str
    template_name: str
    provider_id: str
    model: str
    language: str
    generated_at: str = Field(default_factory=utc_now)


class AudioArtifact(BaseModel):
    file: str
    artifact: Literal["transcript", "summary"]
    engine: str
    voice: str
    rate: int
    generated_at: str = Field(default_factory=utc_now)


class PlaylistRef(BaseModel):
    id: str
    title: str
    source_url: str
    position: int | None = Field(default=None, ge=1)


class PlaylistMeta(BaseModel):
    id: str
    title: str
    source_url: str
    channel: str = ""
    video_count: int = 0
    added_at: str = Field(default_factory=utc_now)


class VideoMeta(BaseModel):
    schema_version: int = 1
    video_id: str
    source_url: str
    title: str
    channel: str = ""
    published_at: str | None = None
    duration_seconds: int | None = None
    thumbnail_file: str | None = None
    thumbnail_url: str | None = None
    added_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    status: str = "queued"
    favorite: bool = False
    archived: bool = False
    tags: list[str] = Field(default_factory=list)
    playlists: list[PlaylistRef] = Field(default_factory=list)
    transcript: TranscriptInfo | None = None
    transcripts: list[TranscriptInfo] = Field(default_factory=list)
    current_summary: SummaryVersion | None = None
    summary_stale: bool = False
    summary_versions: list[SummaryVersion] = Field(default_factory=list)
    prompt_artifacts: list[PromptArtifact] = Field(default_factory=list)
    audio_artifacts: list[AudioArtifact] = Field(default_factory=list)
    available_languages: list[str] = Field(default_factory=list)
    error: str | None = None


class ProviderSettings(BaseModel):
    id: str
    name: str
    kind: Literal["ollama", "openai"]
    base_url: str
    model: str = ""
    enabled: bool = True
    requests_per_minute: int | None = Field(default=None, ge=1, le=10000)
    requests_per_hour: int = Field(default=0, ge=0, le=10_000_000)
    requests_per_day: int = Field(default=0, ge=0, le=100_000_000)
    tokens_per_minute: int = Field(default=0, ge=0, le=100_000_000)
    tokens_per_hour: int = Field(default=0, ge=0, le=1_000_000_000)
    tokens_per_day: int = Field(default=0, ge=0, le=10_000_000_000)
    max_in_flight: int = Field(default=1, ge=1, le=100)
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: int = Field(default=2048, ge=128, le=131072)
    remote: bool = False
    remote_confirmed: bool = False
    has_api_key: bool = False

    @field_validator("base_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.rstrip("/")


class SummaryTemplate(BaseModel):
    id: str
    name_ru: str
    name_en: str
    prompt: str
    builtin: bool = False


class AppSettings(BaseModel):
    schema_version: int = 1
    library_dir: str = "~/Documents/YouTube Summaries"
    interface_language: Literal["ru", "en"] = "en"
    primary_language: str = "en"
    secondary_language: str = "ru"
    summary_language: str = "en"
    allow_any_language: bool = True
    min_download_delay_seconds: int = Field(default=30, ge=0, le=3600)
    max_download_delay_seconds: int = Field(default=90, ge=0, le=3600)
    max_download_retries: int = Field(default=5, ge=0, le=20)
    max_retry_attempts: int = Field(default=3, ge=0, le=10)
    cookie_file: str = ""
    cookie_browser: str = ""
    active_provider_id: str = "ollama"
    parallel_summary_sources: bool = True
    summary_mode: Literal["complete", "cluster"] = "complete"
    summary_template_id: str = "structured"
    chunk_characters: int = Field(default=12000, ge=1000, le=200000)
    cluster_chunk_characters: int = Field(default=2000, ge=500, le=20000)
    cluster_count: int = Field(default=5, ge=2, le=50)
    cluster_samples: int = Field(default=2, ge=1, le=10)
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Literal["mps", "cpu", "cuda"] = "mps"
    asr_engine: Literal["whisperkit", "parakeet"] = "whisperkit"
    asr_language: str = ""
    diarization_enabled: bool = False
    keep_audio: bool = False
    tts_engine: Literal["macos_say"] = "macos_say"
    tts_voice: str = ""
    tts_rate: int = Field(default=190, ge=80, le=500)
    meeting_transcriber_url: str = "http://127.0.0.1:9876"
    meeting_transcriber_token_file: str = "~/Library/Application Support/MeetingTranscriber/.rpc-token"
    log_retention_days: int = Field(default=30, ge=1, le=3650)
    providers: list[ProviderSettings] = Field(default_factory=list)
    templates: list[SummaryTemplate] = Field(default_factory=list)

    @field_validator("max_download_delay_seconds")
    @classmethod
    def valid_delay_range(cls, value: int, info: Any) -> int:
        minimum = info.data.get("min_download_delay_seconds", 0)
        if value < minimum:
            raise ValueError("Maximum delay must be greater than or equal to minimum delay")
        return value


class JobRecord(BaseModel):
    id: str
    video_id: str
    source_url: str
    kind: Literal["process", "refresh", "summarize", "prompt", "tts"] = "process"
    status: str = "queued"
    stage: str = "queued"
    progress: float = Field(default=0, ge=0, le=1)
    position: int = 0
    attempts: int = 0
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    error: str | None = None
    log: list[str] = Field(default_factory=list)
    stage_log: list["JobStageEvent"] = Field(default_factory=list)
    requests_planned: int = Field(default=0, ge=0)
    requests_completed: int = Field(default=0, ge=0)
    summary_source: str | None = None
    provider_id: str | None = None
    provider_name: str | None = None
    model: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str = ""
    execution_state: Literal[
        "blocked",
        "queued",
        "waiting_resource",
        "running",
        "retry_scheduled",
        "cancelling",
        "succeeded",
        "failed",
        "cancelled",
        "skipped",
    ] = "queued"
    waiting_for: dict[str, Any] | None = None
    priority: Literal["low", "normal", "high", "next"] = "normal"


PipelineTaskState = Literal[
    "blocked",
    "queued",
    "waiting_resource",
    "running",
    "retry_scheduled",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
    "skipped",
]


class WorkflowRecord(BaseModel):
    id: str
    video_id: str
    kind: str
    status: str = "waiting"
    priority: Literal["low", "normal", "high", "next"] = "normal"
    settings_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    paused_at: str | None = None
    completed_at: str | None = None


class StageTaskRecord(BaseModel):
    id: str
    workflow_id: str
    video_id: str
    stage: str
    state: PipelineTaskState = "blocked"
    required: bool = True
    progress: float = Field(default=0, ge=0, le=1)
    waiting_for: dict[str, Any] | None = None
    resource_id: str | None = None
    attempt: int = Field(default=0, ge=0)
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None


class PipelineEventRecord(BaseModel):
    sequence: int
    workflow_id: str
    stage_task_id: str | None = None
    video_id: str
    stage: str
    event: str
    from_state: PipelineTaskState | None = None
    to_state: PipelineTaskState | None = None
    message: str = ""
    resource_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class ResourceSnapshot(BaseModel):
    id: str
    label: str
    capacity: int = Field(ge=1)
    in_use: int = Field(ge=0)
    waiting: int = Field(ge=0)
    health: Literal["healthy", "degraded", "unavailable", "paused"] = "healthy"
    owners: list[dict[str, str]] = Field(default_factory=list)


class JobStageEvent(BaseModel):
    """A user-facing checkpoint in a background job."""

    at: str = Field(default_factory=utc_now)
    stage: str
    message: str
    status: Literal["started", "progress", "completed", "failed"] = "progress"
    requests_planned: int = Field(default=0, ge=0)
    requests_completed: int = Field(default=0, ge=0)


class AddVideosRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=200)


class UpdateVideoRequest(BaseModel):
    favorite: bool | None = None
    archived: bool | None = None
    tags: list[str] | None = None


class CreateSummaryRequest(BaseModel):
    provider_id: str | None = None
    model: str | None = None
    template_id: str | None = None
    language: str | None = None
    mode: Literal["complete", "cluster"] | None = None


class CreatePromptRequest(BaseModel):
    template_id: str
    provider_id: str | None = None
    model: str | None = None
    language: str | None = None


class CreateSpeechRequest(BaseModel):
    artifact: Literal["transcript", "summary"]


class ReorderJobsRequest(BaseModel):
    job_ids: list[str]


class ProviderSecretRequest(BaseModel):
    api_key: str


class VideoDetail(BaseModel):
    meta: VideoMeta
    transcript_markdown: str = ""
    transcript_markdowns: dict[str, str] = Field(default_factory=dict)
    summary_markdown: str = ""
    prompt_artifacts: list[PromptArtifact] = Field(default_factory=list)
    folder: str | None = None
