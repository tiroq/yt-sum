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
    language: str
    kind: Literal["author", "automatic", "original", "local_asr"]
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
    tags: list[str] = Field(default_factory=list)
    transcript: TranscriptInfo | None = None
    current_summary: SummaryVersion | None = None
    summary_stale: bool = False
    summary_versions: list[SummaryVersion] = Field(default_factory=list)
    available_languages: list[str] = Field(default_factory=list)
    error: str | None = None


class ProviderSettings(BaseModel):
    id: str
    name: str
    kind: Literal["ollama", "openai"]
    base_url: str
    model: str = ""
    requests_per_minute: int | None = Field(default=None, ge=1, le=10000)
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
    interface_language: Literal["ru", "en"] = "ru"
    primary_language: str = "ru"
    secondary_language: str = "en"
    summary_language: str = "ru"
    allow_any_language: bool = True
    min_download_delay_seconds: int = Field(default=30, ge=0, le=3600)
    max_download_delay_seconds: int = Field(default=90, ge=0, le=3600)
    max_download_retries: int = Field(default=5, ge=0, le=20)
    cookie_file: str = ""
    cookie_browser: str = ""
    active_provider_id: str = "ollama"
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
    kind: Literal["process", "refresh", "summarize"] = "process"
    status: str = "queued"
    stage: str = "queued"
    progress: float = Field(default=0, ge=0, le=1)
    position: int = 0
    attempts: int = 0
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    error: str | None = None
    log: list[str] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)


class AddVideosRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=200)


class UpdateVideoRequest(BaseModel):
    favorite: bool | None = None
    tags: list[str] | None = None


class CreateSummaryRequest(BaseModel):
    provider_id: str | None = None
    model: str | None = None
    template_id: str | None = None
    language: str | None = None
    mode: Literal["complete", "cluster"] | None = None


class ReorderJobsRequest(BaseModel):
    job_ids: list[str]


class ProviderSecretRequest(BaseModel):
    api_key: str


class VideoDetail(BaseModel):
    meta: VideoMeta
    transcript_markdown: str = ""
    summary_markdown: str = ""
    folder: str | None = None
