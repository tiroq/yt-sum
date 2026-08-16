"use client";

import {
  AlertCircle,
  Archive,
  ArchiveX,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  FileText,
  FolderOpen,
  Heart,
  Languages,
  ListChecks,
  LoaderCircle,
  Menu,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Settings as SettingsIcon,
  SlidersHorizontal,
  Sparkles,
  Square,
  Tag,
  Trash2,
  Video,
  Volume2,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { GROUPING_OPTIONS, groupVideos, sortVideos } from "./video-library";
import { formatDuration } from "./duration";
import { clipboardPrefillResult } from "./clipboard-prefill";
import { shouldApplySettingsRefresh } from "./settings-refresh";
import { parseTranscriptMarkdown, transcriptText } from "./transcript";

const API = process.env.NEXT_PUBLIC_YTSUM_API_URL ?? "http://127.0.0.1:8765/api";

type Provider = {
  id: string;
  name: string;
  kind: "ollama" | "openai";
  base_url: string;
  model: string;
  enabled: boolean;
  requests_per_minute: number | null;
  requests_per_hour: number;
  requests_per_day: number;
  tokens_per_minute: number;
  tokens_per_hour: number;
  tokens_per_day: number;
  max_in_flight: number;
  temperature: number;
  max_output_tokens: number;
  remote: boolean;
  remote_confirmed: boolean;
  has_api_key: boolean;
};

type Template = { id: string; name_ru: string; name_en: string; prompt: string; builtin: boolean };

type Settings = {
  schema_version: number;
  library_dir: string;
  interface_language: "ru" | "en";
  primary_language: string;
  secondary_language: string;
  summary_language: string;
  allow_any_language: boolean;
  min_download_delay_seconds: number;
  max_download_delay_seconds: number;
  max_download_retries: number;
  cookie_file: string;
  cookie_browser: string;
  active_provider_id: string;
  parallel_summary_sources: boolean;
  summary_mode: "complete" | "cluster";
  summary_template_id: string;
  chunk_characters: number;
  cluster_chunk_characters: number;
  cluster_count: number;
  cluster_samples: number;
  embedding_model: string;
  embedding_device: "mps" | "cpu" | "cuda";
  asr_engine: "whisperkit" | "parakeet";
  asr_language: string;
  diarization_enabled: boolean;
  keep_audio: boolean;
  tts_engine: "macos_say";
  tts_voice: string;
  tts_rate: number;
  meeting_transcriber_url: string;
  meeting_transcriber_token_file: string;
  log_retention_days: number;
  providers: Provider[];
  templates: Template[];
};

type ProviderStatus = { id: string; enabled: boolean; requests_per_minute: number | null; requests_per_hour: number; requests_per_day: number; tokens_per_minute: number; tokens_per_hour: number; tokens_per_day: number; max_in_flight: number; concurrency_waiting: number; requests_in_window: number; requests_in_hour: number; requests_in_day: number; tokens_in_window: number; tokens_in_hour: number; tokens_in_day: number; waiting: number; token_waiting: number; retry_after_seconds: number; request_interval_seconds: number; token_retry_after_seconds: number; in_flight: number; completed: number; failed: number; last_error: string | null };

type SummaryVersion = { provider_id: string; model: string; template_id: string; language: string; mode: string; generated_at: string; file: string };
type AudioArtifact = { file: string; artifact: "transcript" | "summary"; engine: string; voice: string; rate: number; generated_at: string };
type TranscriptArtifact = { file: string; language: string; kind: string; source: string; role: "original" | "settings"; engine: string | null; segment_count: number; generated_at: string };
type VideoItem = {
  video_id: string;
  source_url: string;
  title: string;
  channel: string;
  published_at: string | null;
  duration_seconds: number | null;
  thumbnail_file: string | null;
  thumbnail_url: string | null;
  status: string;
  favorite: boolean;
  archived: boolean;
  tags: string[];
  playlists: { id: string; title: string; source_url: string; position: number | null }[];
  audio_artifacts: AudioArtifact[];
  added_at: string;
  updated_at: string;
  transcript: { file: string; language: string; kind: string; engine: string | null; segment_count: number } | null;
  transcripts: TranscriptArtifact[];
  current_summary: SummaryVersion | null;
  summary_stale: boolean;
  summary_versions: SummaryVersion[];
  error: string | null;
};
type Playlist = { id: string; title: string; source_url: string; position: number | null; video_count: number; video_ids: string[] };

type PromptArtifact = { id: string; file: string; template_id: string; template_name: string; provider_id: string; model: string; language: string; generated_at: string };
type VideoDetail = { meta: VideoItem & { prompt_artifacts?: PromptArtifact[] }; transcript_markdown: string; transcript_markdowns: Record<string, string>; summary_markdown: string; prompt_artifacts: PromptArtifact[]; folder: string | null };
type JobStageEvent = { at: string; stage: string; message: string; status: "started" | "progress" | "completed" | "failed"; requests_planned: number; requests_completed: number };
type Job = { id: string; workflow_id: string; video_id: string; kind: string; status: string; execution_state: string; waiting_for: { resource_id?: string; label?: string; reason?: string } | null; stage: string; progress: number; error: string | null; log: string[]; stage_log: JobStageEvent[]; requests_planned: number; requests_completed: number; summary_source: string | null; provider_id: string | null; provider_name: string | null; model: string | null };
type QueueHealth = { total: number; queued: number; processing: number; running: number; waiting: number; blocked: number; completed: number; failed: number; cancelled: number; current_stage: string | null; current_video_id: string | null; current_progress: number | null };
type PipelineNode = { id: string; count: number; queued: number; processing: number; running: number; waiting: number; blocked: number; failed: number; completed: number; succeeded: number; cancelled: number; skipped: number; video_ids: string[] };
type ResourceHealth = { id: string; label: string; capacity: number; in_use: number; waiting: number; health: "healthy" | "degraded" | "unavailable" | "paused"; owners: { job_id: string; workflow_id: string; video_id: string; stage: string }[]; requests_per_minute?: number | null; requests_per_hour?: number; requests_per_day?: number; requests_in_window?: number; requests_in_hour?: number; requests_in_day?: number; request_interval_seconds?: number; tokens_per_minute?: number; tokens_per_hour?: number; tokens_per_day?: number; tokens_in_window?: number; tokens_in_hour?: number; tokens_in_day?: number; retry_after_seconds?: number; token_retry_after_seconds?: number; cooldown_seconds?: number; last_error?: string | null };
type StageTask = { id: string; workflow_id: string; video_id: string; stage: string; state: string; progress: number; waiting_for: { resource_id?: string; label?: string; reason?: string } | null; resource_id: string | null; error: string | null; updated_at: string };
type Health = { status: string; queue_paused: boolean; library: string; cursor?: number; queues?: Record<string, QueueHealth>; pipeline?: PipelineNode[]; stage_tasks?: StageTask[]; resources?: ResourceHealth[]; components: Record<string, { ready: boolean; version?: string; engine?: string; address?: string; state?: string; reason?: string }> };
type SourceUpdate = { available: boolean; clean: boolean | null; branch: string | null; upstream: string | null; ahead: number; behind: number; can_pull: boolean; diagnostic: string; updated?: boolean; restart_required?: boolean };

const copy = {
  ru: {
    library: "Библиотека",
    all: "Все видео",
    favorites: "Избранное",
    attention: "Требуют внимания",
    archived: "Архив",
    archive: "Архивировать",
    restore: "Восстановить",
    add: "Добавить видео",
    search: "Поиск по библиотеке",
    sort: "Сортировка",
    grouping: "Группировка",
    alphabetical: "По названию: А–Я",
    alphabeticalReverse: "По названию: Я–А",
    uncategorized: "Без категории",
    summary: "Summary",
    prompts: "Промпты",
    transcript: "Транскрипция",
    details: "Метаданные",
    settings: "Настройки",
    status: "Состояние системы",
    queue: "Очередь",
    emptyTitle: "Добавьте первое видео",
    emptyBody: "Вставьте ссылку YouTube — YT Sum бережно получит транскрипцию и создаст локальный конспект.",
    offline: "Локальный API не запущен",
  },
  en: {
    library: "Library",
    all: "All videos",
    favorites: "Favorites",
    attention: "Needs attention",
    archived: "Archive",
    archive: "Archive",
    restore: "Restore",
    add: "Add video",
    search: "Search library",
    sort: "Sort",
    grouping: "Group",
    alphabetical: "Title: A–Z",
    alphabeticalReverse: "Title: Z–A",
    uncategorized: "Uncategorized",
    summary: "Summary",
    prompts: "Prompts",
    transcript: "Transcript",
    details: "Metadata",
    settings: "Settings",
    status: "System status",
    queue: "Queue",
    emptyTitle: "Add your first video",
    emptyBody: "Paste a YouTube link — YT Sum will carefully collect its transcript and create local notes.",
    offline: "Local API is not running",
  },
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, cache: init?.cache ?? "no-store", headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? response.statusText);
  }
  return response.json();
}

function statusLabel(status: string, language: "ru" | "en") {
  const labels: Record<string, [string, string]> = {
    queued: ["В очереди", "Queued"],
    processing: ["Обрабатывается", "Processing"],
    transcript_ready: ["Текст готов", "Transcript ready"],
    complete: ["Готово", "Ready"],
    stale: ["Summary устарело", "Summary is stale"],
    attention: ["Нужно внимание", "Needs attention"],
    partially_ready: ["Частично готово", "Partially ready"],
  };
  return labels[status]?.[language === "ru" ? 0 : 1] ?? status;
}

function IconButton({ tooltip, className = "", children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { tooltip: string }) {
  const tooltipId = useId();
  return <span className="tooltip-wrap"><button {...props} className={className} aria-describedby={tooltipId}>{children}</button><span className="tooltip" id={tooltipId} role="tooltip">{tooltip}</span></span>;
}

export default function Home() {
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [archivedVideos, setArchivedVideos] = useState<VideoItem[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [playlistId, setPlaylistId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const settingsDirtyRef = useRef(false);
  const jobsRefreshRevisionRef = useRef(0);
  const libraryRefreshRevisionRef = useRef(0);
  const [health, setHealth] = useState<Health | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<VideoDetail | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "favorite" | "attention" | "archived" | "playlist">("all");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [grouping, setGrouping] = useState<"none" | "tag" | "topic">("none");
  const [tab, setTab] = useState<"summary" | "prompts" | "transcript" | "details">("summary");
  const [promptResult, setPromptResult] = useState<{ artifact: PromptArtifact; markdown: string } | null>(null);
  const [view, setView] = useState<"library" | "settings" | "status">("library");
  const [addOpen, setAddOpen] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [links, setLinks] = useState("");
  const addDialogTriggerRef = useRef<HTMLElement | null>(null);
  const [transcriptView, setTranscriptView] = useState<"continuous" | "structured">("continuous");
  const [transcriptFile, setTranscriptFile] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [online, setOnline] = useState(true);

  const language = settings?.interface_language ?? "ru";
  const t = copy[language];

  useEffect(() => {
    setTranscriptFile(detail?.meta.transcript?.file ?? detail?.meta.transcripts?.[0]?.file ?? "");
  }, [detail?.meta.video_id, detail?.meta.transcript?.file, detail?.meta.transcripts]);

  useEffect(() => {
    const savedSort = window.localStorage.getItem("yt-sum.library.sort");
    const savedGrouping = window.localStorage.getItem("yt-sum.library.grouping");
    const savedTranscriptView = window.localStorage.getItem("yt-sum.transcript.view");
    if (savedSort === "asc" || savedSort === "desc") setSortDirection(savedSort);
    if (savedGrouping === "none" || savedGrouping === "tag" || savedGrouping === "topic") setGrouping(savedGrouping);
    if (savedTranscriptView === "continuous" || savedTranscriptView === "structured") setTranscriptView(savedTranscriptView);
  }, []);

  useEffect(() => {
    window.localStorage.setItem("yt-sum.library.sort", sortDirection);
  }, [sortDirection]);

  useEffect(() => {
    window.localStorage.setItem("yt-sum.library.grouping", grouping);
  }, [grouping]);

  useEffect(() => {
    window.localStorage.setItem("yt-sum.transcript.view", transcriptView);
  }, [transcriptView]);

  const refresh = useCallback(async () => {
    const jobsRefreshRevision = jobsRefreshRevisionRef.current;
    const libraryRefreshRevision = ++libraryRefreshRevisionRef.current;
    try {
      const [videoPayload, archivedPayload, jobPayload, settingsPayload] = await Promise.all([
        request<{ items: VideoItem[] }>(`/videos${query.trim() ? `?query=${encodeURIComponent(query.trim())}` : ""}`),
        request<{ items: VideoItem[] }>(`/videos?archived=true${query.trim() ? `&query=${encodeURIComponent(query.trim())}` : ""}`),
        request<{ items: Job[] }>("/jobs"),
        request<Settings>("/settings"),
      ]);
      // A polling refresh may have started before an archive/restore PATCH.
      // Never let that older response overwrite the newer local state.
      if (libraryRefreshRevision !== libraryRefreshRevisionRef.current) return;
      // Keep the two views mutually exclusive even when talking to an older
      // API instance that does not yet apply the archived query parameter.
      setVideos(videoPayload.items.filter((video) => !video.archived));
      setArchivedVideos(archivedPayload.items.filter((video) => video.archived));
      if (jobsRefreshRevision === jobsRefreshRevisionRef.current) setJobs(jobPayload.items);
      if (shouldApplySettingsRefresh(settingsDirtyRef.current)) setSettings(settingsPayload);
      setOnline(true);
      setSelectedId((current) => current ?? videoPayload.items[0]?.video_id ?? null);
      void request<Health>("/health").then(setHealth).catch(() => setHealth(null));
      void request<{ items: Playlist[] }>("/playlists").then((payload) => setPlaylists(payload.items)).catch(() => setPlaylists([]));
    } catch (cause) {
      setOnline(false);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [query]);

  const updateSettings = useCallback((value: Settings) => {
    settingsDirtyRef.current = true;
    setSettings(value);
  }, []);

  const refreshSavedSettings = useCallback(async () => {
    settingsDirtyRef.current = false;
    await refresh();
  }, [refresh]);

  const refreshDetail = useCallback(async (videoId: string | null) => {
    if (!videoId) {
      setDetail(null);
      return;
    }
    try {
      setDetail(await request<VideoDetail>(`/videos/${videoId}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const source = new EventSource(`${API}/diagnostics/stream?after=${health?.cursor ?? 0}`);
    let pending = false;
    source.addEventListener("pipeline", () => {
      if (pending) return;
      pending = true;
      window.setTimeout(() => {
        pending = false;
        void request<Health>("/diagnostics/snapshot").then((snapshot) => {
          setHealth((current) => !current?.cursor || (snapshot.cursor ?? 0) >= current.cursor ? snapshot : current);
        }).catch(() => undefined);
        void request<{ items: Job[] }>("/jobs").then((payload) => setJobs(payload.items)).catch(() => undefined);
      }, 150);
    });
    return () => source.close();
  }, [health?.cursor]);

  useEffect(() => {
    void refreshDetail(selectedId);
  }, [selectedId, refreshDetail, videos]);

  const visibleVideos = useMemo(() => {
    const filtered = (filter === "archived" ? archivedVideos : videos).filter((video) => {
      if (filter === "favorite" && !video.favorite) return false;
      if (filter === "attention" && video.status !== "attention") return false;
      if (filter === "playlist" && !video.playlists.some((playlist) => playlist.id === playlistId)) return false;
      return true;
    });
    return sortVideos(filtered, sortDirection);
  }, [videos, archivedVideos, filter, playlistId, sortDirection]);

  const videoGroups = useMemo(
    () => groupVideos(visibleVideos, grouping, t.uncategorized),
    [visibleVideos, grouping, t.uncategorized],
  );

  const activeJobs = jobs.filter((job) => ["queued", "processing"].includes(job.status));
  const selectedSummaryJob = useMemo(() => jobs.filter((job) => job.video_id === selectedId && job.kind === "summarize").sort((left, right) => (left.status === "processing" ? -1 : right.status === "processing" ? 1 : 0))[0], [jobs, selectedId]);

  function openAddDialog(event: React.MouseEvent<HTMLElement>) {
    addDialogTriggerRef.current = event.currentTarget;
    setAddOpen(true);
  }

  function closeAddDialog() {
    setAddOpen(false);
    window.requestAnimationFrame(() => addDialogTriggerRef.current?.focus());
  }

  async function addVideos() {
    const urls = links.split(/\n+/).map((value) => value.trim()).filter(Boolean);
    if (!urls.length) return;
    try {
      const payload = await request<{ existing: string[]; errors: { error: string }[] }>("/videos", { method: "POST", body: JSON.stringify({ urls }) });
      setLinks("");
      closeAddDialog();
      if (payload.existing[0]) setSelectedId(payload.existing[0]);
      if (payload.errors.length) setError(payload.errors.map((item) => item.error).join("\n"));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function toggleFavorite() {
    if (!detail) return;
    await request(`/videos/${detail.meta.video_id}`, { method: "PATCH", body: JSON.stringify({ favorite: !detail.meta.favorite }) });
    await refresh();
  }

  async function setArchived(video: VideoItem, archived: boolean) {
    const nextVideo = { ...video, archived };
    // Update both local buckets immediately so the card moves as soon as the
    // action is activated; the refresh below then confirms the persisted state.
    if (archived) {
      setVideos((items) => items.filter((item) => item.video_id !== video.video_id));
      setArchivedVideos((items) => [nextVideo, ...items.filter((item) => item.video_id !== video.video_id)]);
    } else {
      setArchivedVideos((items) => items.filter((item) => item.video_id !== video.video_id));
      setVideos((items) => [nextVideo, ...items.filter((item) => item.video_id !== video.video_id)]);
    }
    try {
      await request(`/videos/${video.video_id}`, { method: "PATCH", body: JSON.stringify({ archived }) });
      if (archived && selectedId === video.video_id) {
        setSelectedId(null);
        setDetail(null);
      }
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function editTags() {
    if (!detail) return;
    const value = window.prompt(language === "ru" ? "Теги через запятую" : "Comma-separated tags", detail.meta.tags.join(", "));
    if (value === null) return;
    await request(`/videos/${detail.meta.video_id}`, { method: "PATCH", body: JSON.stringify({ tags: value.split(",").map((tagName) => tagName.trim()).filter(Boolean) }) });
    await refresh();
  }

  async function resummarize() {
    if (!detail) return;
    await request(`/videos/${detail.meta.video_id}/summaries`, { method: "POST", body: "{}" });
    await refresh();
  }

  async function runPrompt(templateId: string) {
    if (!detail) return;
    try {
      await request(`/videos/${detail.meta.video_id}/prompts`, { method: "POST", body: JSON.stringify({ template_id: templateId }) });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function openPromptArtifact(artifact: PromptArtifact) {
    if (!detail) return;
    try {
      setPromptResult(await request<{ artifact: PromptArtifact; markdown: string }>(`/videos/${detail.meta.video_id}/prompts/${artifact.id}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function createSpeech(artifact: "transcript" | "summary") {
    if (!detail) return;
    try {
      await request(`/videos/${detail.meta.video_id}/speech`, { method: "POST", body: JSON.stringify({ artifact }) });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function refreshVideo() {
    if (!detail) return;
    try {
      const result = await request<{ created: boolean }>(`/videos/${detail.meta.video_id}/refresh`, { method: "POST" });
      setNotice(result.created
        ? (language === "ru" ? "Транскрипция поставлена на переобработку." : "Transcript reprocessing has been queued.")
        : (language === "ru" ? "Это видео уже находится в очереди на переобработку." : "This video is already queued for reprocessing."));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function openArtifactsFolder() {
    if (!detail) return;
    try {
      await request(`/videos/${detail.meta.video_id}/folder/open`, { method: "POST" });
      setNotice(language === "ru" ? "Папка артефактов открыта в Finder." : "Artifacts folder opened in Finder.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function deleteVideo() {
    if (!detail || !window.confirm(language === "ru" ? "Убрать видео из библиотеки?" : "Remove this video from the library?")) return;
    const deleteFiles = window.confirm(language === "ru" ? "Также удалить локальную папку и все файлы?" : "Also delete the local folder and all files?");
    await request(`/videos/${detail.meta.video_id}?delete_files=${deleteFiles}`, { method: "DELETE" });
    setSelectedId(null);
    setDetail(null);
    await refresh();
  }

  async function deleteJobHistory(job: Job) {
    if (!window.confirm(language === "ru" ? "Удалить эту запись из истории обработки? Видео и его файлы останутся на месте." : "Remove this processing-history entry? The video and its files will stay in place.")) return;
    // Invalidate an in-flight poll before changing local state, so a stale
    // response cannot make the removed entry reappear.
    jobsRefreshRevisionRef.current += 1;
    try {
      await request(`/jobs/${job.id}`, { method: "DELETE" });
      setJobs((current) => current.filter((item) => item.id !== job.id));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      await refresh();
    }
  }

  async function clearVideoHistory(videoId: string) {
    const inactive = jobs.filter((job) => job.video_id === videoId && !["queued", "processing"].includes(job.status));
    if (!inactive.length || !window.confirm(language === "ru" ? `Удалить неактивные записи обработки (${inactive.length})? Активные задачи останутся в очереди.` : `Remove ${inactive.length} inactive processing records? Active tasks will remain queued.`)) return;
    jobsRefreshRevisionRef.current += 1;
    try {
      await request(`/videos/${videoId}/jobs`, { method: "DELETE" });
      setJobs((current) => current.filter((job) => job.video_id !== videoId || ["queued", "processing"].includes(job.status)));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      await refresh();
    }
  }

  return (
    <main className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="brand-row">
          <div className="brand-mark"><Sparkles size={19} strokeWidth={2.4} /></div>
          <div><div className="brand-name">YT Sum</div><div className="brand-subtitle">local intelligence</div></div>
          <IconButton className="icon-button mobile-only" onClick={() => setSidebarOpen(false)} aria-label="Close" tooltip="Закрыть меню. Фокус остаётся на странице."><X size={18} /></IconButton>
        </div>

        <button className="add-button" onClick={openAddDialog}><Plus size={18} />{t.add}</button>

        <nav className="nav-stack" aria-label="Primary navigation">
          <button className={view === "library" && filter === "all" ? "nav-item active" : "nav-item"} onClick={() => { setView("library"); setFilter("all"); }}><Archive size={18} />{t.all}<span>{videos.length}</span></button>
          <button className={view === "library" && filter === "favorite" ? "nav-item active" : "nav-item"} onClick={() => { setView("library"); setFilter("favorite"); }}><Heart size={18} />{t.favorites}<span>{videos.filter((v) => v.favorite).length}</span></button>
          <button className={view === "library" && filter === "attention" ? "nav-item active" : "nav-item"} onClick={() => { setView("library"); setFilter("attention"); }}><AlertCircle size={18} />{t.attention}<span>{videos.filter((v) => v.status === "attention").length}</span></button>
          <button className={view === "library" && filter === "archived" ? "nav-item active" : "nav-item"} onClick={() => { setView("library"); setFilter("archived"); }}><Archive size={18} />{t.archived}<span>{archivedVideos.length}</span></button>
          {playlists.length ? <div className="playlist-nav"><div className="sidebar-section-label">{language === "ru" ? "Плейлисты" : "Playlists"}</div>{playlists.map((playlist) => <button key={playlist.id} className={view === "library" && filter === "playlist" && playlistId === playlist.id ? "nav-item active" : "nav-item"} onClick={() => { setView("library"); setFilter("playlist"); setPlaylistId(playlist.id); }}><ListChecks size={18} /><span title={playlist.title}>{playlist.title}</span><span>{playlist.video_count}</span></button>)}</div> : null}
        </nav>

        <div className="sidebar-section-label">{t.library}</div>
        <div className="search-box"><Search size={16} /><input id="search-library" name="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t.search} /></div>
        <div className="library-controls" aria-label={language === "ru" ? "Настройки списка видео" : "Video list settings"}>
          <label><span>{t.sort}</span><select value={sortDirection} onChange={(event) => setSortDirection(event.target.value as "asc" | "desc")} aria-label={t.sort}><option value="asc">{t.alphabetical}</option><option value="desc">{t.alphabeticalReverse}</option></select></label>
          <label><span>{t.grouping}</span><select value={grouping} onChange={(event) => setGrouping(event.target.value as "none" | "tag" | "topic")} aria-label={t.grouping}>{GROUPING_OPTIONS.map((option) => <option key={option.id} value={option.id}>{language === "ru" ? option.label : option.labelEn}</option>)}</select></label>
        </div>
        <div className="video-list">
          {videoGroups.map((group) => <section className="video-group" key={group.id}>{group.label ? <h2>{group.label}<span>{group.videos.length}</span></h2> : null}{group.videos.map((video) => (
            <div key={`${group.id}-${video.video_id}`} className={`video-card ${selectedId === video.video_id && view === "library" ? "selected" : ""}`}>
              <button className="video-card-main" onClick={() => { setSelectedId(video.video_id); setView("library"); setSidebarOpen(false); }}>
                <div className="thumb-wrap"><img src={video.thumbnail_file ? `${API}/videos/${video.video_id}/thumbnail` : `https://i.ytimg.com/vi/${video.video_id}/mqdefault.jpg`} alt="" />{video.duration_seconds !== null ? <span>{formatDuration(video.duration_seconds)}</span> : null}</div>
                <div className="video-card-copy"><strong>{video.title}</strong><small>{video.channel || statusLabel(video.status, language)}</small><div className={`status-dot ${video.status}`} /> </div>
              </button>
              <IconButton className="quick-archive-button" onClick={(event) => { event.stopPropagation(); void setArchived(video, !video.archived); }} aria-label={video.archived ? t.restore : t.archive} tooltip={video.archived ? "Вернуть видео в библиотеку. Оно снова появится среди обычных видео." : "Архивировать видео. Оно исчезнет из обычного списка, но файлы сохранятся."}>{video.archived ? <ArchiveX size={15} /> : <Archive size={15} />}</IconButton>
            </div>
          ))}</section>)}
        </div>

        <div className="sidebar-footer">
          <button className={view === "settings" ? "footer-button active" : "footer-button"} onClick={() => { setView("settings"); setSidebarOpen(false); }}><SettingsIcon size={18} />{t.settings}</button>
          <button className={view === "status" ? "footer-button active" : "footer-button"} onClick={() => { setView("status"); setSidebarOpen(false); }}><span className={`connection-dot ${online ? "online" : "offline"}`} />{online ? t.status : t.offline}</button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <IconButton className="icon-button mobile-only" onClick={() => setSidebarOpen(true)} aria-label="Menu" tooltip="Открыть меню навигации. Фокус перейдёт в боковую панель."><Menu size={20} /></IconButton>
          <div className="breadcrumb"><span>YT Sum</span><span>/</span><strong>{view === "library" ? detail?.meta.title ?? t.library : view === "settings" ? t.settings : t.status}</strong></div>
          <div className="topbar-actions">
            <div className={`online-pill ${online ? "" : "offline"}`}>{online ? <Wifi size={14} /> : <WifiOff size={14} />}{online ? "Local" : "Offline"}</div>
            <button className="queue-button" onClick={() => setQueueOpen(!queueOpen)}><ListChecks size={17} />{t.queue}{activeJobs.length ? <span>{activeJobs.length}</span> : null}</button>
          </div>
        </header>

        {!online ? <OfflineState message={error || t.offline} onRetry={refresh} language={language} /> : view === "settings" && settings ? (
          <SettingsView settings={settings} setSettings={updateSettings} onSaved={refreshSavedSettings} language={language} />
        ) : view === "status" ? (
          <div className="status-page status-layout"><SystemStatus health={health} settings={settings} language={language} onSelectVideo={(videoId) => { setSelectedId(videoId); setView("library"); }} onRescan={async () => { await request("/library/rescan", { method: "POST" }); await refresh(); }} /><SourceUpdatePanel language={language} /></div>
        ) : detail ? (
          <>
            <section className="video-hero">
              <div className="hero-thumb"><img src={detail.meta.thumbnail_file ? `${API}/videos/${detail.meta.video_id}/thumbnail` : `https://i.ytimg.com/vi/${detail.meta.video_id}/hqdefault.jpg`} alt="" /><span className="tooltip-wrap"><a href={detail.meta.source_url} target="_blank" rel="noreferrer" aria-label="Open video" aria-describedby="open-video-tooltip"><Play size={20} fill="currentColor" /></a><span className="tooltip" id="open-video-tooltip" role="tooltip">Открыть видео на YouTube. Откроется новая вкладка.</span></span></div>
              <div className="hero-copy"><div className="eyebrow"><span className={`status-badge ${detail.meta.status}`}>{statusLabel(detail.meta.status, language)}</span>{detail.meta.transcript ? <span><Languages size={13} />{detail.meta.transcript.language.toUpperCase()} · {detail.meta.transcript.kind}</span> : null}</div><h1>{detail.meta.title}</h1><p>{detail.meta.channel} {detail.meta.published_at ? `· ${detail.meta.published_at}` : ""} {detail.meta.duration_seconds !== null ? `· ${formatDuration(detail.meta.duration_seconds)}` : ""}</p><div className="tag-row">{detail.meta.tags.map((tagName) => <span key={tagName}><Tag size={11} />{tagName}</span>)}</div></div>
              <div className="hero-actions"><IconButton className={`icon-button ${detail.meta.favorite ? "favorite" : ""}`} onClick={toggleFavorite} aria-label={detail.meta.favorite ? "Remove from favorites" : "Add to favorites"} tooltip={detail.meta.favorite ? "Убрать из избранного. Видео исчезнет из фильтра «Избранное»." : "Добавить в избранное. Видео появится в фильтре «Избранное»."}><Heart size={19} fill={detail.meta.favorite ? "currentColor" : "none"} /></IconButton><IconButton className="icon-button" onClick={editTags} aria-label="Edit tags" tooltip="Изменить теги. Сохранённые теги будут заменены."><Tag size={18} /></IconButton><IconButton className="icon-button" onClick={refreshVideo} aria-label="Refresh" tooltip="Обновить видео. Сбор данных будет поставлен в очередь."><RefreshCw size={18} /></IconButton><IconButton className="icon-button danger-hover" onClick={deleteVideo} aria-label="Delete" tooltip="Удалить видео. Затем можно удалить и локальные файлы."><Trash2 size={18} /></IconButton></div>
            </section>

            <nav className="tabs">
              <button className={tab === "summary" ? "active" : ""} onClick={() => setTab("summary")}><Sparkles size={16} />{t.summary}</button>
              <button className={tab === "prompts" ? "active" : ""} onClick={() => setTab("prompts")}><ListChecks size={16} />{t.prompts}</button>
              <button className={tab === "transcript" ? "active" : ""} onClick={() => setTab("transcript")}><FileText size={16} />{t.transcript}</button>
              <button className={tab === "details" ? "active" : ""} onClick={() => setTab("details")}><SlidersHorizontal size={16} />{t.details}</button>
            </nav>

            <section className="content-scroll">
              {tab === "summary" ? <><SummaryProgressCard job={selectedSummaryJob} language={language} /><MarkdownPanel markdown={detail.summary_markdown} empty={language === "ru" ? "Summary ещё не создано." : "Summary has not been created yet."} action={<button className="secondary-button" onClick={resummarize}><RotateCcw size={16} />{language === "ru" ? "Создать заново" : "Regenerate"}</button>} /><SpeechPanel detail={detail} artifact="summary" onCreate={createSpeech} language={language} /></> : null}
              {tab === "prompts" ? <PromptPanel templates={settings?.templates ?? []} artifacts={detail.prompt_artifacts ?? []} selected={promptResult} language={language} onRun={runPrompt} onOpen={openPromptArtifact} /> : null}
              {tab === "transcript" ? <><TranscriptPanel detail={detail} file={transcriptFile} setFile={setTranscriptFile} view={transcriptView} setView={setTranscriptView} language={language} onReprocess={refreshVideo} /><SpeechPanel detail={detail} artifact="transcript" onCreate={createSpeech} language={language} /></> : null}
              {tab === "details" ? <DetailsPanel detail={detail} jobs={jobs.filter((job) => job.video_id === detail.meta.video_id)} language={language} onDeleteJob={deleteJobHistory} onClearHistory={clearVideoHistory} onOpenFolder={openArtifactsFolder} /> : null}
            </section>
          </>
        ) : (
          <EmptyState onAdd={openAddDialog} title={t.emptyTitle} body={t.emptyBody} />
        )}
      </section>

      {addOpen ? <AddDialog links={links} setLinks={setLinks} onClose={closeAddDialog} onAdd={addVideos} language={language} /> : null}
      {queueOpen ? <QueuePanel jobs={jobs} videos={videos} paused={health?.queue_paused ?? false} close={() => setQueueOpen(false)} onSelectVideo={(videoId) => { setSelectedId(videoId); setView("library"); setQueueOpen(false); }} refresh={refresh} language={language} /> : null}
      {error && online ? <div className="toast"><AlertCircle size={18} /><span>{error}</span><IconButton onClick={() => setError("")} aria-label="Dismiss error" tooltip="Закрыть сообщение об ошибке. Выполненное действие не отменяется."><X size={16} /></IconButton></div> : null}
      {notice ? <div className="toast success" role="status"><CheckCircle2 size={18} /><span>{notice}</span><IconButton onClick={() => setNotice("")} aria-label="Dismiss notification" tooltip="Закрыть уведомление."><X size={16} /></IconButton></div> : null}
    </main>
  );
}

function MarkdownPanel({ markdown, empty, action }: { markdown: string; empty: string; action: React.ReactNode }) {
  return <article className="document-card"><div className="document-toolbar"><div><span className="overline">AI NOTES</span><h2>Summary</h2></div>{action}</div>{markdown ? <div className="markdown"><ReactMarkdown components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer">{children}</a> }}>{markdown.replace(/^---\n[\s\S]*?\n---\n/, "")}</ReactMarkdown></div> : <div className="empty-inline"><Sparkles size={28} /><p>{empty}</p></div>}</article>;
}

function PromptPanel({ templates, artifacts, selected, language, onRun, onOpen }: { templates: Template[]; artifacts: PromptArtifact[]; selected: { artifact: PromptArtifact; markdown: string } | null; language: "ru" | "en"; onRun: (templateId: string) => void; onOpen: (artifact: PromptArtifact) => void }) {
  return <div className="details-grid"><section className="info-card"><span className="overline">REUSABLE PROMPTS</span><h2>{language === "ru" ? "Запустить отдельный промпт" : "Run a standalone prompt"}</h2><p className="muted">{language === "ru" ? "Каждый запуск независим и сохраняется отдельным Markdown-файлом в папке видео." : "Each run is independent and saved as its own Markdown file in the video folder."}</p><div className="template-grid">{templates.map((template) => <div className="template-card" key={template.id}><strong>{language === "ru" ? template.name_ru : template.name_en}</strong><button className="secondary-button" onClick={() => onRun(template.id)}><Play size={15} />{language === "ru" ? "Запустить" : "Run"}</button></div>)}</div></section><section className="info-card"><span className="overline">ARTIFACTS</span><h2>{language === "ru" ? "Результаты" : "Results"}</h2>{artifacts.length ? <div className="nav-stack">{artifacts.map((artifact) => <button className={selected?.artifact.id === artifact.id ? "nav-item active" : "nav-item"} key={artifact.id} onClick={() => onOpen(artifact)}><FileText size={16} /><span>{artifact.template_name}</span><small>{new Date(artifact.generated_at).toLocaleString()}</small></button>)}</div> : <p className="muted">{language === "ru" ? "Пока нет отдельных результатов." : "No standalone results yet."}</p>}{selected ? <div className="markdown"><ReactMarkdown>{selected.markdown.replace(/^---\n[\s\S]*?\n---\n/, "")}</ReactMarkdown></div> : null}</section></div>;
}

function SpeechPanel({ detail, artifact, onCreate, language }: { detail: VideoDetail; artifact: "transcript" | "summary"; onCreate: (artifact: "transcript" | "summary") => void; language: "ru" | "en" }) {
  const audio = detail.meta.audio_artifacts?.find((item) => item.artifact === artifact);
  const sourceReady = artifact === "summary" ? Boolean(detail.summary_markdown) : Boolean(detail.transcript_markdown);
  const active = false;
  return <section className="info-card narration-card"><div><span className="overline">TEXT TO SPEECH</span><h2>{language === "ru" ? "Озвучивание" : "Narration"}</h2><p className="muted">{audio ? `${audio.voice} · ${audio.rate} wpm` : (language === "ru" ? "Создайте локальный M4A-файл для этого текста." : "Create a local M4A file for this text.")}</p></div>{audio ? <audio controls preload="metadata" src={`${API}/videos/${detail.meta.video_id}/speech/${artifact}`}><track kind="captions" srcLang={language} label={language === "ru" ? "Исходный текст" : "Source text"} /></audio> : null}<button className="secondary-button" onClick={() => onCreate(artifact)} disabled={!sourceReady || active}><Volume2 size={16} />{audio ? (language === "ru" ? "Создать заново" : "Regenerate") : (language === "ru" ? "Озвучить" : "Generate audio")}</button></section>;
}

function SummaryProgressCard({ job, language }: { job: Job | undefined; language: "ru" | "en" }) {
  if (!job) return null;
  const requestCount = `${job.requests_completed} / ${job.requests_planned || "—"}`;
  const events = job.stage_log.length ? job.stage_log : job.log.map((message, index) => ({ at: String(index), stage: job.stage, message, status: "progress" as const, requests_planned: job.requests_planned, requests_completed: job.requests_completed }));
  return <article className="info-card"><span className="overline">SUMMARY ACTIVITY</span><h2>{language === "ru" ? "Ход суммаризации" : "Summarization progress"}</h2><div className="detail-row"><span>{language === "ru" ? "Текущий этап" : "Current stage"}</span><strong>{job.stage}</strong></div><div className="detail-row"><span>{language === "ru" ? "Запросы: выполнено / запланировано" : "Requests: completed / planned"}</span><strong>{requestCount}</strong></div><div className="detail-row"><span>{language === "ru" ? "Источник" : "Source"}</span><strong>{job.summary_source ?? "—"}</strong></div><div className="detail-row"><span>{language === "ru" ? "Провайдер / модель" : "Provider / model"}</span><strong>{[job.provider_name, job.model].filter(Boolean).join(" / ") || "—"}</strong></div>{job.error ? <p className="job-error">{job.error}</p> : null}<details className="job-history"><summary>{language === "ru" ? `Журнал этапов (${events.length})` : `Stage journal (${events.length})`}</summary><div className="job-log"><pre>{events.map((event) => `${event.at} · ${event.stage} · ${event.requests_completed}/${event.requests_planned || "—"} — ${event.message}`).join("\n")}</pre></div></details></article>;
}

function TranscriptPanel({ detail, file, setFile, view, setView, language, onReprocess }: { detail: VideoDetail; file: string; setFile: (value: string) => void; view: "continuous" | "structured"; setView: (value: "continuous" | "structured") => void; language: "ru" | "en"; onReprocess: () => void }) {
  const markdown = detail.transcript_markdowns?.[file] ?? detail.transcript_markdown;
  const segments = parseTranscriptMarkdown(markdown);
  const plain = transcriptText(segments);
  const labels = language === "ru" ? { continuous: "Сплошной текст", structured: "По сегментам" } : { continuous: "Continuous", structured: "By segment" };
  const artifacts = detail.meta.transcripts ?? [];
  return <article className="document-card transcript-document"><div className="document-toolbar"><div><span className="overline">SOURCE</span><h2>{language === "ru" ? "Полная транскрипция" : "Full transcript"}</h2></div><div className="document-actions"><button type="button" className="secondary-button" onClick={onReprocess}><RefreshCw size={16} />{language === "ru" ? "Переобработать" : "Reprocess"}</button><div className="view-toggle" role="group" aria-label={language === "ru" ? "Вид транскрипции" : "Transcript view"}><button type="button" className={view === "continuous" ? "active" : ""} aria-pressed={view === "continuous"} onClick={() => setView("continuous")}>{labels.continuous}</button><button type="button" className={view === "structured" ? "active" : ""} aria-pressed={view === "structured"} onClick={() => setView("structured")}>{labels.structured}</button></div></div></div>{artifacts.length > 1 ? <label className="field full"><span>{language === "ru" ? "Вариант транскрипции" : "Transcript version"}</span><select value={file} onChange={(event) => setFile(event.target.value)}>{artifacts.map((artifact) => <option value={artifact.file} key={artifact.file}>{artifact.role === "original" ? (language === "ru" ? "Исходник" : "Original") : (language === "ru" ? "Язык настроек" : "Settings language")} · {artifact.language.toUpperCase()} · {artifact.kind} · {artifact.source}</option>)}</select></label> : null}{markdown ? view === "continuous" ? <div className="plain-transcript">{plain}</div> : <div className="structured-transcript">{segments.map((segment, index) => <div className="transcript-segment" key={`${segment.timestamp}-${index}`}><a className="transcript-timestamp" href={segment.href ?? undefined} target="_blank" rel="noreferrer">{segment.timestamp}</a><div className="transcript-segment-text">{segment.speaker ? <strong>{segment.speaker}:</strong> : null}{segment.text}</div></div>)}</div> : <div className="empty-inline"><FileText size={28} /><p>{language === "ru" ? "Транскрипция ещё не готова." : "Transcript is not ready yet."}</p></div>}</article>;
}

function DetailsPanel({ detail, jobs, language, onDeleteJob, onClearHistory, onOpenFolder }: { detail: VideoDetail; jobs: Job[]; language: "ru" | "en"; onDeleteJob: (job: Job) => void; onClearHistory: (videoId: string) => void; onOpenFolder: () => void }) {
  // Video metadata written before playlists and summary history were introduced
  // does not contain these arrays. Keep older local libraries readable.
  const summaryVersions = detail.meta.summary_versions ?? [];
  const playlists = detail.meta.playlists ?? [];
  const rows = [
    ["YouTube ID", detail.meta.video_id],
    [language === "ru" ? "Папка" : "Folder", detail.folder ?? "—"],
    [language === "ru" ? "Язык текста" : "Transcript language", detail.meta.transcript?.language ?? "—"],
    [language === "ru" ? "Источник текста" : "Transcript source", detail.meta.transcript?.kind ?? "—"],
    [language === "ru" ? "Варианты текста" : "Transcript versions", String(detail.meta.transcripts?.length ?? 0)],
    [language === "ru" ? "Модель summary" : "Summary model", detail.meta.current_summary?.model ?? "—"],
    [language === "ru" ? "Версий summary" : "Summary versions", String(summaryVersions.length + (detail.meta.current_summary ? 1 : 0))],
    [language === "ru" ? "Плейлисты" : "Playlists", playlists.length ? playlists.map((playlist) => `${playlist.title}${playlist.position ? ` #${playlist.position}` : ""}`).join(", ") : "—"],
  ];
  const inactiveCount = jobs.filter((job) => !["queued", "processing"].includes(job.status)).length;
  return <div className="details-grid"><section className="info-card"><span className="overline">FILE-FIRST</span><h2>{language === "ru" ? "Данные видео" : "Video data"}</h2>{rows.map(([label, value]) => <div className="detail-row" key={label}><span>{label}</span><strong title={value}>{value}</strong></div>)}<button className="secondary-button" onClick={onOpenFolder} disabled={!detail.folder}><FolderOpen size={16} />{language === "ru" ? "Открыть папку артефактов" : "Open artifacts folder"}</button></section><section className="info-card"><div className="section-heading compact"><div><span className="overline">PROCESSING</span><h2>{language === "ru" ? "История обработки" : "Processing history"}</h2></div><button className="text-button danger-text" onClick={() => onClearHistory(detail.meta.video_id)} disabled={!inactiveCount} title={language === "ru" ? "Удалить завершённые, отменённые и прерванные записи" : "Remove completed, cancelled, and interrupted records"}><Trash2 size={14} />{language === "ru" ? "Очистить" : "Clear"}</button></div>{jobs.length ? jobs.map((job) => <details className="job-history" key={job.id}><summary><div className={`job-state ${job.status}`}><Clock3 size={15} /></div><div><strong>{job.stage}</strong><p>{job.error || `${Math.round(job.progress * 100)}%`}</p></div>{!["queued", "processing"].includes(job.status) ? <button className="mini-button danger-hover job-history-delete" onClick={(event) => { event.preventDefault(); event.stopPropagation(); onDeleteJob(job); }} aria-label={language === "ru" ? "Удалить запись истории" : "Remove history entry"} title={language === "ru" ? "Удалить запись истории" : "Remove history entry"}><X size={14} /></button> : null}</summary>{job.log.length ? <div className="job-log"><button className="text-button" onClick={() => { void navigator.clipboard.writeText(job.log.join("\n")); }}><FileText size={13} />{language === "ru" ? "Копировать лог" : "Copy log"}</button><pre>{job.log.join("\n")}</pre></div> : null}</details>) : <p className="muted">{language === "ru" ? "Задач пока нет." : "No jobs yet."}</p>}</section></div>;
}

function EmptyState({ onAdd, title, body }: { onAdd: (event: React.MouseEvent<HTMLButtonElement>) => void; title: string; body: string }) {
  return <div className="empty-state"><div className="empty-orbit"><Video size={34} /><span /><span /></div><h1>{title}</h1><p>{body}</p><button className="primary-button" onClick={onAdd}><Plus size={17} />Добавить ссылку</button><div className="feature-hints"><span><CheckCircle2 size={15} />Markdown first</span><span><CheckCircle2 size={15} />Local models</span><span><CheckCircle2 size={15} />Slow & respectful</span></div></div>;
}

function OfflineState({ message, onRetry, language }: { message: string; onRetry: () => void; language: "ru" | "en" }) {
  return <div className="empty-state offline-state"><div className="empty-orbit danger"><WifiOff size={32} /></div><h1>{language === "ru" ? "Сервис не отвечает" : "Service is unavailable"}</h1><p>{message}</p><button className="primary-button" onClick={onRetry}><RefreshCw size={17} />{language === "ru" ? "Проверить снова" : "Try again"}</button><code>./scripts/dev.sh</code></div>;
}

function AddDialog({ links, setLinks, onClose, onAdd, language }: { links: string; setLinks: (value: string) => void; onClose: () => void; onAdd: () => void; language: "ru" | "en" }) {
  const [clipboardMessage, setClipboardMessage] = useState("");
  const linksRef = useRef(links);
  const setLinksRef = useRef(setLinks);
  const languageRef = useRef(language);

  useEffect(() => {
    linksRef.current = links;
    setLinksRef.current = setLinks;
    languageRef.current = language;
  }, [language, links, setLinks]);

  useEffect(() => {
    let active = true;
    async function prefillFromClipboard() {
      const currentLanguage = languageRef.current;
      if (!navigator.clipboard?.readText) {
        setClipboardMessage(currentLanguage === "ru" ? "Не удалось прочитать буфер обмена. Вставьте ссылку вручную." : "Could not read the clipboard. Paste the link manually.");
        return;
      }
      try {
        const result = clipboardPrefillResult(linksRef.current, await navigator.clipboard.readText());
        if (!active || result.kind === "ignored") return;
        if (result.kind === "prefilled") {
          setLinksRef.current(result.value);
          setClipboardMessage(currentLanguage === "ru" ? "Ссылка YouTube добавлена из буфера обмена." : "YouTube link added from the clipboard.");
        }
      } catch (failure) {
        const result = clipboardPrefillResult(linksRef.current, "", failure);
        if (!active) return;
        setClipboardMessage(result.kind === "permission-denied"
          ? (currentLanguage === "ru" ? "Нет доступа к буферу обмена. Вставьте ссылку вручную." : "Clipboard access was denied. Paste the link manually.")
          : (currentLanguage === "ru" ? "Не удалось прочитать буфер обмена. Вставьте ссылку вручную." : "Could not read the clipboard. Paste the link manually."));
      }
    }
    void prefillFromClipboard();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const linksField = document.getElementById("youtube-links") as HTMLTextAreaElement | null;
    linksField?.focus();

    function keepFocusInDialog(event: KeyboardEvent) {
      const dialog = document.querySelector<HTMLElement>("[role=dialog][aria-modal=true]");
      if (!dialog) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = dialog.querySelectorAll<HTMLElement>("button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), [href]");
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", keepFocusInDialog);
    return () => document.removeEventListener("keydown", keepFocusInDialog);
  }, [onClose]);

  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="add-dialog-title"><div className="modal-heading"><div><span className="overline">YOUTUBE</span><h2 id="add-dialog-title">{language === "ru" ? "Добавить в библиотеку" : "Add to library"}</h2></div><IconButton className="icon-button" onClick={onClose} aria-label="Close" tooltip="Закрыть окно. Несохранённые ссылки будут потеряны."><X size={18} /></IconButton></div><p>{language === "ru" ? "Вставьте одну или несколько ссылок — по одной на строку." : "Paste one or more links, one per line."}</p><textarea id="youtube-links" name="youtube-links" value={links} onChange={(event) => setLinks(event.target.value)} placeholder="https://www.youtube.com/watch?v=…" rows={7} aria-label={language === "ru" ? "Ссылки YouTube" : "YouTube links"} />{clipboardMessage ? <p className="clipboard-status" role="status">{clipboardMessage}</p> : null}<div className="modal-note"><Clock3 size={16} /><span>{language === "ru" ? "Все обращения yt-dlp выполняются строго по одному; распознавание и модели работают в независимых очередях." : "All yt-dlp calls are strictly serialized; transcription and model work use independent queues."}</span></div><div className="modal-actions"><button className="ghost-button" onClick={onClose}>{language === "ru" ? "Отмена" : "Cancel"}</button><button className="primary-button" onClick={onAdd} disabled={!links.trim()}><Plus size={17} />{language === "ru" ? "Добавить в очередь" : "Add to queue"}</button></div></section></div>;
}

function QueuePanel({ jobs, videos, paused, close, onSelectVideo, refresh, language }: { jobs: Job[]; videos: VideoItem[]; paused: boolean; close: () => void; onSelectVideo: (videoId: string) => void; refresh: () => Promise<void>; language: "ru" | "en" }) {
  const downloadJobs = jobs.filter((job) => ["process", "refresh"].includes(job.kind));
  const llmJobs = jobs.filter((job) => ["summarize", "prompt"].includes(job.kind));
  const ttsJobs = jobs.filter((job) => job.kind === "tts");
  async function queueAction(path: string) {
    try { await request(path, { method: "POST" }); } catch { /* refresh below shows the authoritative state */ }
    try { await refresh(); } catch { /* the next poll will retry */ }
  }
  async function moveJob(job: Job, delta: number) {
    const lane = ["process", "refresh"].includes(job.kind) ? downloadJobs : llmJobs;
    const queued = lane.filter((item) => item.status === "queued");
    const index = queued.findIndex((item) => item.id === job.id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= queued.length) return;
    [queued[index], queued[target]] = [queued[target], queued[index]];
    try {
      await request("/jobs/reorder", { method: "POST", body: JSON.stringify({ job_ids: queued.map((item) => item.id) }) });
      await refresh();
    } catch { /* keep the current order until the next refresh */ }
  }
  const renderLane = (laneJobs: Job[], title: string) => <section className="queue-lane"><div className="queue-lane-heading"><h3>{title}</h3><span>{laneJobs.filter((job) => ["queued", "processing"].includes(job.status)).length}</span></div><div className="queue-items">{laneJobs.length ? laneJobs.map((job) => { const video = videos.find((item) => item.video_id === job.video_id); const canStop = ["queued", "processing"].includes(job.status); const canRetry = ["attention", "cancelled"].includes(job.status); return <div className="queue-item" key={job.id}><div className="queue-item-top"><div className={`job-icon ${job.status}`}>{job.execution_state === "running" ? <LoaderCircle size={16} className="spin" /> : job.status === "complete" ? <CheckCircle2 size={16} /> : job.status === "attention" ? <AlertCircle size={16} /> : <Clock3 size={16} />}</div><div className="queue-job-copy"><button className="queue-video-link" onClick={() => onSelectVideo(job.video_id)} title={language === "ru" ? "Открыть видео" : "Open video"}>{video?.title ?? job.video_id}</button><small>{job.stage}{["summarize", "prompt"].includes(job.kind) ? ` · ${job.requests_completed}/${job.requests_planned || "—"}` : ""}</small>{job.waiting_for?.reason ? <small>{job.waiting_for.reason}</small> : null}{job.provider_name || job.model ? <small>{[job.provider_name, job.model].filter(Boolean).join(" / ")}</small> : null}</div>{job.status === "queued" ? <div className="reorder-buttons"><button className="mini-button" onClick={() => void moveJob(job, -1)} aria-label="Move up"><ChevronUp size={13} /></button><button className="mini-button" onClick={() => void moveJob(job, 1)} aria-label="Move down"><ChevronDown size={13} /></button></div> : null}{canStop || canRetry ? <button className="mini-button" onClick={() => void queueAction(canRetry ? `/jobs/${job.id}/retry` : `/jobs/${job.id}/cancel`)} aria-label={canRetry ? "Retry task" : "Stop task"}>{canRetry ? <RotateCcw size={14} /> : <Square size={13} />}</button> : null}</div><div className="progress-track"><span style={{ width: `${job.progress * 100}%` }} /></div>{job.error ? <p className="job-error">{job.error}</p> : null}</div>; }) : <div className="queue-empty"><CheckCircle2 size={24} /><p>{language === "ru" ? "Очередь пуста" : "Queue is empty"}</p></div>}</div></section>;
  return <aside className="queue-panel"><div className="queue-heading"><div><span className="overline">BACKGROUND</span><h2>{language === "ru" ? "Очереди обработки" : "Processing queues"}</h2></div><button className="icon-button" onClick={close}><X size={18} /></button></div><div className="queue-controls"><button className="queue-control" onClick={() => void queueAction(paused ? "/jobs/resume" : "/jobs/pause")}>{paused ? <Play size={16} /> : <Pause size={16} />}{paused ? (language === "ru" ? "Продолжить" : "Resume") : (language === "ru" ? "Пауза" : "Pause")}</button><button className="queue-stop-all" onClick={() => { if (window.confirm(language === "ru" ? "Остановить все активные и ожидающие задачи?" : "Stop all active and queued jobs?")) void queueAction("/jobs/stop"); }}>{language === "ru" ? "Остановить всё" : "Stop all"}</button></div>{renderLane(downloadJobs, language === "ru" ? "Получение данных" : "Data acquisition")}{renderLane(llmJobs, language === "ru" ? "Языковые модели" : "Language models")}{renderLane(ttsJobs, language === "ru" ? "Озвучивание" : "Text to speech")}</aside>;
}

function ToggleSwitch({ checked, label, onChange }: { checked: boolean; label: string; onChange: (value: boolean) => void }) {
  return <button type="button" className={`toggle-switch ${checked ? "on" : ""}`} role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)} title={label}><span className="toggle-switch-track"><span className="toggle-switch-knob" /></span><span className="toggle-switch-label">{label}</span></button>;
}

function ProviderUsageStatus({ status, language }: { status?: ProviderStatus; language: "ru" | "en" }) {
  if (!status) return <div className="source-status">{language === "ru" ? "Статус загружается…" : "Loading status…"}</div>;
  const usage = [
    status.requests_per_minute ? `${status.requests_in_window}/${status.requests_per_minute} RPM` : `${status.requests_in_window}`,
    status.requests_per_hour ? `${status.requests_in_hour}/${status.requests_per_hour} RPH` : "",
    status.requests_per_day ? `${status.requests_in_day}/${status.requests_per_day} RPD` : "",
    status.request_interval_seconds ? `${language === "ru" ? "интервал" : "interval"} ${status.request_interval_seconds}s` : "",
    status.tokens_per_minute ? `${status.tokens_in_window}/${status.tokens_per_minute} TPM` : "",
    status.tokens_per_hour ? `${status.tokens_in_hour}/${status.tokens_per_hour} TPH` : "",
    status.tokens_per_day ? `${status.tokens_in_day}/${status.tokens_per_day} TPD` : "",
  ].filter(Boolean).join(" · ");
  const waiting = status.waiting + status.token_waiting;
  return <div className="source-status">{status.in_flight ? `${language === "ru" ? "В работе" : "In flight"}: ${status.in_flight}` : `${language === "ru" ? "За минуту" : "Last minute"}: ${usage}`}{waiting ? ` · ${language === "ru" ? "ожидает" : "waiting"}: ${waiting}` : ""}{status.retry_after_seconds ? ` · ${language === "ru" ? "RPM лимит через" : "RPM limit clears in"} ${formatDuration(status.retry_after_seconds)}` : ""}{status.token_retry_after_seconds ? ` · ${language === "ru" ? "TPM лимит через" : "TPM limit clears in"} ${formatDuration(status.token_retry_after_seconds)}` : ""}{status.failed ? ` · ${language === "ru" ? "ошибок" : "errors"}: ${status.failed}` : ""}</div>;
}

function SettingsView({ settings, setSettings, onSaved, language }: { settings: Settings; setSettings: (value: Settings) => void; onSaved: () => Promise<void>; language: "ru" | "en" }) {
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [secret, setSecretValue] = useState<Record<string, string>>({});
  const [sourceStatus, setSourceStatus] = useState<Record<string, ProviderStatus>>({});
  const refreshStatuses = useCallback(async () => {
    try {
      const payload = await request<{ items: ProviderStatus[] }>("/providers/status");
      setSourceStatus(Object.fromEntries(payload.items.map((item) => [item.id, item])));
    } catch {
      // Older API processes may not expose provider status yet. The settings
      // page remains usable and will retry on the next polling interval.
      setSourceStatus({});
    }
  }, []);
  useEffect(() => { void refreshStatuses(); const timer = window.setInterval(() => { void refreshStatuses(); }, 2000); return () => window.clearInterval(timer); }, [refreshStatuses]);
  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => setSettings({ ...settings, [key]: value });
  const updateProvider = (id: string, patch: Partial<Provider>) => update("providers", settings.providers.map((provider) => provider.id === id ? { ...provider, ...patch } : provider));
  const updateTemplate = (id: string, patch: Partial<Template>) => update("templates", settings.templates.map((template) => template.id === id ? { ...template, ...patch } : template));

  async function save() { setSaving(true); try { await request("/settings", { method: "PUT", body: JSON.stringify(settings) }); for (const [id, apiKey] of Object.entries(secret)) if (apiKey) await request(`/providers/${id}/secret`, { method: "POST", body: JSON.stringify({ api_key: apiKey }) }); setSecretValue({}); await onSaved(); } finally { setSaving(false); } }
  async function discover(provider: Provider) {
    try {
      const payload = await request<{ items: string[] }>(`/providers/${provider.id}/models`, { method: "POST" });
      setModels({ ...models, [provider.id]: payload.items });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      window.alert(language === "ru"
        ? `Не удалось получить список моделей для «${provider.name}». Проверьте адрес endpoint и доступность сервиса.\n\n${message}`
        : `Could not load models for “${provider.name}”. Check the endpoint URL and that the service is running.\n\n${message}`);
    }
  }
  function addProvider() { const id = `provider-${Date.now()}`; update("providers", [...settings.providers, { id, name: "New endpoint", kind: "openai", base_url: "http://127.0.0.1:8000/v1", model: "", enabled: true, requests_per_minute: null, requests_per_hour: 0, requests_per_day: 0, tokens_per_minute: 0, tokens_per_hour: 0, tokens_per_day: 0, max_in_flight: 1, temperature: 0, max_output_tokens: 2048, remote: false, remote_confirmed: true, has_api_key: false }]); }
  function removeProvider(provider: Provider) {
    if (!window.confirm(language === "ru" ? `Удалить endpoint «${provider.name}»?` : `Delete endpoint “${provider.name}”?`)) return;
    const providers = settings.providers.filter((item) => item.id !== provider.id);
    const activeProviderId = settings.active_provider_id === provider.id ? (providers[0]?.id ?? "") : settings.active_provider_id;
    setSettings({ ...settings, providers, active_provider_id: activeProviderId });
    setSecretValue(Object.fromEntries(Object.entries(secret).filter(([id]) => id !== provider.id)));
  }
  function addTemplate() { const id = `template-${Date.now()}`; update("templates", [...settings.templates, { id, name_ru: "Новый шаблон", name_en: "New template", prompt: "Create a faithful Markdown summary in {language}.", builtin: false }]); update("summary_template_id", id); }

  return <div className="settings-page"><div className="page-heading"><div><span className="overline">LOCAL-FIRST</span><h1>{language === "ru" ? "Настройки" : "Settings"}</h1><p>{language === "ru" ? "Всё хранится на этом Mac. Секреты — только в Связке ключей." : "Everything stays on this Mac. Secrets are stored only in Keychain."}</p></div><button className="primary-button" onClick={save} disabled={saving}>{saving ? <LoaderCircle size={16} className="spin" /> : <CheckCircle2 size={16} />}{language === "ru" ? "Сохранить" : "Save"}</button></div>
    <div className="settings-layout">
      <section className="settings-card"><div className="settings-card-title"><FolderOpen size={19} /><div><h2>{language === "ru" ? "Библиотека и языки" : "Library and languages"}</h2><p>Markdown + JSON</p></div></div><label className="field full"><span>{language === "ru" ? "Папка библиотеки" : "Library folder"}</span><input id="library-dir" name="library-dir" value={settings.library_dir} onChange={(e) => update("library_dir", e.target.value)} /></label><div className="field-grid"><label className="field"><span>{language === "ru" ? "Основной текст" : "Primary transcript"}</span><input value={settings.primary_language} onChange={(e) => update("primary_language", e.target.value)} /></label><label className="field"><span>{language === "ru" ? "Запасной текст" : "Fallback transcript"}</span><input value={settings.secondary_language} onChange={(e) => update("secondary_language", e.target.value)} /></label><label className="field"><span>{language === "ru" ? "Язык summary" : "Summary language"}</span><input value={settings.summary_language} onChange={(e) => update("summary_language", e.target.value)} /></label><label className="field"><span>{language === "ru" ? "Интерфейс" : "Interface"}</span><select value={settings.interface_language} onChange={(e) => update("interface_language", e.target.value as "ru" | "en")}><option value="ru">Русский</option><option value="en">English</option></select></label></div></section>

      <section className="settings-card"><div className="settings-card-title"><Clock3 size={19} /><div><h2>{language === "ru" ? "Бережная загрузка" : "Respectful downloading"}</h2><p>yt-dlp</p></div></div><div className="field-grid"><label className="field"><span>{language === "ru" ? "Минимальная пауза, сек" : "Minimum delay, sec"}</span><input id="min-delay" name="min-delay" type="number" value={settings.min_download_delay_seconds} onChange={(e) => update("min_download_delay_seconds", Number(e.target.value))} /></label><label className="field"><span>{language === "ru" ? "Максимальная пауза, сек" : "Maximum delay, sec"}</span><input id="max-delay" name="max-delay" type="number" value={settings.max_download_delay_seconds} onChange={(e) => update("max_download_delay_seconds", Number(e.target.value))} /></label></div><label className="field full"><span>cookies.txt</span><input id="cookie-file" name="cookie-file" value={settings.cookie_file} onChange={(e) => update("cookie_file", e.target.value)} placeholder="~/Downloads/cookies.txt" /></label><label className="field full"><span>{language === "ru" ? "Cookies браузера" : "Browser cookies"}</span><select value={settings.cookie_browser} onChange={(e) => update("cookie_browser", e.target.value)}><option value="">{language === "ru" ? "Не использовать" : "Disabled"}</option><option value="chrome">Chrome</option><option value="safari">Safari</option><option value="firefox">Firefox</option></select></label></section>

      <section className="settings-card wide"><div className="settings-card-title"><Sparkles size={19} /><div><h2>{language === "ru" ? "Источники summary" : "Summary sources"}</h2><p>{language === "ru" ? "Параллельное планирование с отдельными RPM" : "Parallel scheduling with per-source RPM"}</p></div><button className="text-button" onClick={addProvider}><Plus size={15} />Endpoint</button></div><label className="check-row source-pool-toggle"><input type="checkbox" checked={settings.parallel_summary_sources} onChange={(e) => update("parallel_summary_sources", e.target.checked)} />{language === "ru" ? "Распределять фрагменты между всеми включёнными источниками" : "Distribute chunks across all enabled sources"}</label><div className="provider-grid">{settings.providers.map((provider) => { const status = sourceStatus[provider.id]; return <div className={`provider-card ${settings.active_provider_id === provider.id ? "active" : ""}`} key={provider.id}><div className="provider-top"><button className="provider-radio" onClick={() => update("active_provider_id", provider.id)}><span />{settings.active_provider_id === provider.id ? (language === "ru" ? "По умолчанию" : "Default") : (language === "ru" ? "Выбрать" : "Select")}</button><select value={provider.kind} onChange={(e) => updateProvider(provider.id, { kind: e.target.value as "ollama" | "openai" })}><option value="ollama">Ollama</option><option value="openai">OpenAI-compatible</option></select><button className="mini-button danger-hover" onClick={() => removeProvider(provider)} aria-label={language === "ru" ? `Удалить endpoint ${provider.name}` : `Delete endpoint ${provider.name}`} title={language === "ru" ? "Удалить endpoint" : "Delete endpoint"}><Trash2 size={13} /></button></div><input className="provider-name" value={provider.name} onChange={(e) => updateProvider(provider.id, { name: e.target.value })} /><label className="field full"><span>Endpoint</span><input value={provider.base_url} onChange={(e) => updateProvider(provider.id, { base_url: e.target.value })} /></label><div className="model-row"><label className="field"><span>{language === "ru" ? "Модель" : "Model"}</span><input list={`models-${provider.id}`} value={provider.model} onChange={(e) => updateProvider(provider.id, { model: e.target.value })} /><datalist id={`models-${provider.id}`}>{models[provider.id]?.map((name) => <option value={name} key={name} />)}</datalist></label><button className="discover-button" onClick={() => discover(provider)} aria-label="Discover models"><RefreshCw size={15} /></button></div><div className="field-grid"><label className="field"><span>RPM</span><input type="number" placeholder="∞" value={provider.requests_per_minute ?? ""} onChange={(e) => updateProvider(provider.id, { requests_per_minute: e.target.value ? Number(e.target.value) : null })} /></label><label className="field"><span>RPH</span><input type="number" min="0" placeholder="∞" value={provider.requests_per_hour || ""} onChange={(e) => updateProvider(provider.id, { requests_per_hour: e.target.value ? Number(e.target.value) : 0 })} /></label><label className="field"><span>RPD</span><input type="number" min="0" placeholder="∞" value={provider.requests_per_day || ""} onChange={(e) => updateProvider(provider.id, { requests_per_day: e.target.value ? Number(e.target.value) : 0 })} /></label><label className="field"><span>TPM</span><input type="number" min="0" placeholder="∞" value={provider.tokens_per_minute || ""} onChange={(e) => updateProvider(provider.id, { tokens_per_minute: e.target.value ? Number(e.target.value) : 0 })} /></label><label className="field"><span>TPH</span><input type="number" min="0" placeholder="∞" value={provider.tokens_per_hour || ""} onChange={(e) => updateProvider(provider.id, { tokens_per_hour: e.target.value ? Number(e.target.value) : 0 })} /></label><label className="field"><span>TPD</span><input type="number" min="0" placeholder="∞" value={provider.tokens_per_day || ""} onChange={(e) => updateProvider(provider.id, { tokens_per_day: e.target.value ? Number(e.target.value) : 0 })} /></label><label className="field"><span>{language === "ru" ? "Одновременно" : "In flight"}</span><input type="number" min="1" value={provider.max_in_flight} onChange={(e) => updateProvider(provider.id, { max_in_flight: Number(e.target.value) })} /></label><label className="field"><span>Temperature</span><input type="number" step="0.1" value={provider.temperature} onChange={(e) => updateProvider(provider.id, { temperature: Number(e.target.value) })} /></label></div><label className="field full"><span>API key · Keychain</span><input type="password" value={secret[provider.id] ?? ""} onChange={(e) => setSecretValue({ ...secret, [provider.id]: e.target.value })} placeholder={provider.has_api_key ? "••••••••••••" : "Optional"} /></label><ToggleSwitch checked={provider.enabled} onChange={(enabled) => updateProvider(provider.id, { enabled })} label={language === "ru" ? "Использовать endpoint в обработке" : "Use endpoint for processing"} /><ProviderUsageStatus status={status} language={language} /><label className="check-row"><input type="checkbox" checked={provider.remote} onChange={(e) => updateProvider(provider.id, { remote: e.target.checked, remote_confirmed: !e.target.checked })} />{language === "ru" ? "Это удалённый endpoint" : "This is a remote endpoint"}</label>{provider.remote ? <label className="check-row privacy-check"><input type="checkbox" checked={provider.remote_confirmed} onChange={(e) => updateProvider(provider.id, { remote_confirmed: e.target.checked })} />{language === "ru" ? "Разрешаю отправку текста этому провайдеру" : "Allow transcript upload to this provider"}</label> : null}</div>; })}</div></section>

      <section className="settings-card"><div className="settings-card-title"><FileText size={19} /><div><h2>{language === "ru" ? "Суммаризация" : "Summarization"}</h2><p>Full coverage by default</p></div></div><label className="field full"><span>{language === "ru" ? "Режим" : "Mode"}</span><select id="summary-mode" name="summary-mode" value={settings.summary_mode} onChange={(e) => update("summary_mode", e.target.value as "complete" | "cluster")}><option value="complete">{language === "ru" ? "Полное покрытие (map-reduce)" : "Complete coverage (map-reduce)"}</option><option value="cluster">{language === "ru" ? "Быстрый кластерный (lossy)" : "Fast clustering (lossy)"}</option></select></label><label className="field full"><span>{language === "ru" ? "Шаблон" : "Template"}</span><select id="summary-template" name="summary-template" value={settings.summary_template_id} onChange={(e) => update("summary_template_id", e.target.value)}>{settings.templates.map((template) => <option key={template.id} value={template.id}>{language === "ru" ? template.name_ru : template.name_en}</option>)}</select></label><label className="field full"><span>{language === "ru" ? "Размер фрагмента, символов" : "Chunk size, characters"}</span><input id="chunk-chars" name="chunk-chars" type="number" value={settings.chunk_characters} onChange={(e) => update("chunk_characters", Number(e.target.value))} /></label></section>

      <section className="settings-card"><div className="settings-card-title"><Languages size={19} /><div><h2>{language === "ru" ? "Распознавание аудио" : "Audio transcription"}</h2><p>Meeting Transcriber · CoreML</p></div></div><label className="field full"><span>{language === "ru" ? "Движок" : "Engine"}</span><select id="asr-engine" name="asr-engine" value={settings.asr_engine} onChange={(e) => update("asr_engine", e.target.value as "whisperkit" | "parakeet")}><option value="whisperkit">WhisperKit</option><option value="parakeet">Parakeet TDT v3</option></select></label><label className="field full"><span>Automation API</span><input id="transcriber-url" name="transcriber-url" value={settings.meeting_transcriber_url} onChange={(e) => update("meeting_transcriber_url", e.target.value)} /></label><label className="check-row"><input type="checkbox" checked={settings.diarization_enabled} onChange={(e) => update("diarization_enabled", e.target.checked)} />{language === "ru" ? "Разделять спикеров" : "Speaker diarization"}</label><label className="check-row"><input type="checkbox" checked={settings.keep_audio} onChange={(e) => update("keep_audio", e.target.checked)} />{language === "ru" ? "Сохранять аудио" : "Keep audio files"}</label></section>
      <section className="settings-card"><div className="settings-card-title"><Volume2 size={19} /><div><h2>{language === "ru" ? "Озвучивание текста" : "Text-to-Speech"}</h2><p>macOS Speech · local M4A</p></div></div><label className="field full"><span>{language === "ru" ? "Движок" : "Engine"}</span><select value={settings.tts_engine} onChange={(e) => update("tts_engine", e.target.value as "macos_say")}><option value="macos_say">macOS Speech</option></select></label><div className="field-grid"><label className="field"><span>{language === "ru" ? "Голос (пусто — системный)" : "Voice (blank = system default)"}</span><input value={settings.tts_voice} onChange={(e) => update("tts_voice", e.target.value)} placeholder="Milena" /></label><label className="field"><span>{language === "ru" ? "Скорость, слов/мин" : "Rate, words/min"}</span><input type="number" min="80" max="500" value={settings.tts_rate} onChange={(e) => update("tts_rate", Number(e.target.value))} /></label></div></section>

      <section className="settings-card wide"><div className="settings-card-title"><FileText size={19} /><div><h2>{language === "ru" ? "Шаблоны промптов" : "Prompt templates"}</h2><p>{language === "ru" ? "Встроенные и пользовательские инструкции для summary и отдельных запусков" : "Built-in and custom instructions for summaries and standalone runs"}</p></div><button className="text-button" onClick={addTemplate}><Plus size={15} />{language === "ru" ? "Шаблон" : "Template"}</button></div><div className="template-grid">{settings.templates.map((template) => <div className={`template-card ${settings.summary_template_id === template.id ? "active" : ""}`} key={template.id}><div className="template-title-row"><button className="provider-radio" onClick={() => update("summary_template_id", template.id)}><span />{settings.summary_template_id === template.id ? (language === "ru" ? "Активный" : "Active") : (language === "ru" ? "Выбрать" : "Select")}</button>{!template.builtin ? <button className="mini-button danger-hover" onClick={() => update("templates", settings.templates.filter((item) => item.id !== template.id))} aria-label="Delete template"><Trash2 size={13} /></button> : null}</div><div className="field-grid"><label className="field"><span>RU</span><input value={template.name_ru} onChange={(e) => updateTemplate(template.id, { name_ru: e.target.value })} disabled={template.builtin} /></label><label className="field"><span>EN</span><input value={template.name_en} onChange={(e) => updateTemplate(template.id, { name_en: e.target.value })} disabled={template.builtin} /></label></div><label className="field full"><span>Prompt</span><textarea value={template.prompt} onChange={(e) => updateTemplate(template.id, { prompt: e.target.value })} disabled={template.builtin} rows={4} /></label></div>)}</div></section>
    </div>
  </div>;
}

function SourceUpdatePanel({ language }: { language: "ru" | "en" }) {
  const [status, setStatus] = useState<SourceUpdate | null>(null);
  const [action, setAction] = useState<"idle" | "checking" | "pulling" | "restarting">("checking");
  const [error, setError] = useState<string | null>(null);
  const check = useCallback(async () => { setAction("checking"); setError(null); try { setStatus(await request<SourceUpdate>("/system/source-update")); setAction("idle"); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setAction("idle"); } }, []);
  useEffect(() => { void check(); }, [check]);
  async function pull() { setAction("pulling"); setError(null); try { setStatus(await request<SourceUpdate>("/system/source-update/pull", { method: "POST" })); setAction("idle"); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setAction("idle"); } }
  async function restart() { setAction("restarting"); try { await request("/system/restart", { method: "POST" }); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setAction("idle"); } }
  const busy = action !== "idle";
  return <section className="info-card status-info"><h2>{language === "ru" ? "Обновление приложения" : "Application updates"}</h2>{status ? <><div className="detail-row"><span>{language === "ru" ? "Ветка" : "Branch"}</span><strong>{status.branch ?? "—"}</strong></div><div className="detail-row"><span>{language === "ru" ? "Рабочее дерево" : "Working tree"}</span><strong>{status.clean === null ? "—" : status.clean ? (language === "ru" ? "Чистое" : "Clean") : (language === "ru" ? "Есть локальные изменения" : "Local changes")}</strong></div><div className="detail-row"><span>{language === "ru" ? "Upstream-коммиты" : "Upstream commits"}</span><strong>{status.upstream ? `+${status.behind} / −${status.ahead}` : "—"}</strong></div><p>{status.diagnostic}</p></> : <p>{language === "ru" ? "Проверяем Git-источник…" : "Checking Git source…"}</p>}{error ? <p className="error-text">{error}</p> : null}<div className="page-actions"><button className="secondary-button" onClick={check} disabled={busy}>{action === "checking" ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />}{language === "ru" ? "Проверить" : "Check"}</button><button className="secondary-button" onClick={pull} disabled={!status?.can_pull || busy}>{action === "pulling" ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />}{language === "ru" ? "Сделать pull" : "Pull updates"}</button>{status?.restart_required ? <button className="secondary-button" onClick={restart} disabled={busy}>{action === "restarting" ? <LoaderCircle size={16} className="spin" /> : <RotateCcw size={16} />}{language === "ru" ? "Перезапустить API" : "Restart API"}</button> : null}</div></section>;
}

function PipelineGraph({ pipeline, tasks, language, onSelectVideo }: { pipeline?: PipelineNode[]; tasks?: StageTask[]; language: "ru" | "en"; onSelectVideo: (videoId: string) => void }) {
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const labels: Record<string, string> = language === "ru" ? { queued: "Входная очередь", metadata: "Метаданные", thumbnail: "Превью", "transcript-selection": "Выбор дорожек", "subtitle-download": "Субтитры", "audio-download": "Аудио", transcribing: "Распознавание", "transcript-normalize": "Нормализация", "transcript-ready": "Текст готов", summarizing: "Подготовка summary", "summary-map": "Обработка фрагментов", "summary-reduce": "Сборка результата", "summary-final": "Финальный summary", "running-prompt": "Отдельные промпты", "speech-synthesis": "Озвучивание", "saving-audio": "Сохранение аудио" } : { queued: "Input queue", metadata: "Metadata", thumbnail: "Preview", "transcript-selection": "Track selection", "subtitle-download": "Subtitles", "audio-download": "Audio", transcribing: "Transcription", "transcript-normalize": "Normalization", "transcript-ready": "Transcript ready", summarizing: "Summary preparation", "summary-map": "Process chunks", "summary-reduce": "Merge result", "summary-final": "Final summary", "running-prompt": "Reusable prompts", "speech-synthesis": "Speech synthesis", "saving-audio": "Save audio" };
  const empty = (id: string): PipelineNode => ({ id, count: 0, queued: 0, processing: 0, running: 0, waiting: 0, blocked: 0, failed: 0, completed: 0, succeeded: 0, cancelled: 0, skipped: 0, video_ids: [] });
  const lookup = new Map((pipeline ?? []).map((node) => [node.id, node]));
  const node = (id: string) => {
    const item = lookup.get(id) ?? empty(id);
    const title = item.video_ids.length ? `${item.video_ids.length} ${language === "ru" ? "видео" : "videos"}` : (language === "ru" ? "Нет текущих задач" : "No current tasks");
    return <button type="button" className={`pipeline-node ${item.running ? "active" : ""} ${item.failed ? "failed" : ""} ${selectedStage === id ? "selected" : ""}`} title={title} key={id} onClick={() => setSelectedStage((current) => current === id ? null : id)}><div className="pipeline-node-top"><strong>{labels[id] ?? id}</strong><b>{item.count}</b></div><div className="pipeline-node-stats"><span><i className="state-dot running" />{item.running} {language === "ru" ? "выполняется" : "running"}</span><span><i className="state-dot waiting" />{item.waiting} {language === "ru" ? "ждёт ресурс" : "waiting"}</span><span>{item.queued} {language === "ru" ? "в очереди" : "queued"}</span><span>{item.blocked} {language === "ru" ? "заблокировано" : "blocked"}</span>{item.failed ? <span className="failed-count">{item.failed} {language === "ru" ? "ошибок" : "failed"}</span> : null}</div>{item.video_ids[0] ? <small>{item.video_ids.length} {language === "ru" ? "связанных видео" : "linked videos"}</small> : null}</button>;
  };
  const arrow = <span className="pipeline-arrow" aria-hidden="true">→</span>;
  const selectedTasks = selectedStage ? (tasks ?? []).filter((task) => task.stage.split(":", 1)[0] === selectedStage) : [];
  return <section className="pipeline-panel"><div className="section-heading"><div><span className="overline">PIPELINE</span><h2>{language === "ru" ? "Маршруты обработки" : "Processing routes"}</h2></div><span className="queue-global-state">Live</span></div><div className="pipeline-dag"><div className="pipeline-row pipeline-ingress">{node("queued")}{arrow}{node("metadata")}{arrow}{node("transcript-selection")}</div><div className="pipeline-side-row"><span className="pipeline-branch-label">{language === "ru" ? "Не блокирует текст" : "Non-blocking"}</span>{node("thumbnail")}</div><div className="pipeline-branch-group"><div className="pipeline-branch-label">{language === "ru" ? "Доступные дорожки" : "Available tracks"}</div><div className="pipeline-row">{node("subtitle-download")}{arrow}</div><div className="pipeline-branch-label fallback">Fallback</div><div className="pipeline-row">{node("audio-download")}{arrow}{node("transcribing")}{arrow}</div><div className="pipeline-convergence">{node("transcript-normalize")}{arrow}{node("transcript-ready")}</div></div><div className="pipeline-artifact-branches"><div className="pipeline-artifact-row"><span className="pipeline-branch-label">Summary</span>{node("summarizing")}{arrow}{node("summary-map")}{arrow}{node("summary-reduce")}{arrow}{node("summary-final")}</div><div className="pipeline-artifact-row"><span className="pipeline-branch-label">Artifacts</span>{node("running-prompt")}</div><div className="pipeline-artifact-row"><span className="pipeline-branch-label">TTS</span>{node("speech-synthesis")}{arrow}{node("saving-audio")}</div></div></div>{selectedStage ? <div className="pipeline-task-list"><div className="pipeline-task-heading"><strong>{labels[selectedStage] ?? selectedStage}</strong><span>{selectedTasks.length}</span></div>{selectedTasks.length ? selectedTasks.map((task) => <button type="button" key={task.id} onClick={() => onSelectVideo(task.video_id)}><span><strong>{task.video_id}</strong><small>{task.waiting_for?.reason ?? task.error ?? task.resource_id ?? task.state}</small></span><b className={`task-state ${task.state}`}>{task.state}</b></button>) : <p>{language === "ru" ? "Текущих задач на этом этапе нет." : "No current tasks at this stage."}</p>}</div> : null}</section>;
}

function ResourcePanel({ resources, language }: { resources?: ResourceHealth[]; language: "ru" | "en" }) {
  if (!resources?.length) return null;
  return <section className="resource-panel"><div className="section-heading"><div><span className="overline">RESOURCES</span><h2>{language === "ru" ? "Ресурсы и ограничения" : "Resources and limits"}</h2></div></div><div className="resource-grid">{resources.map((resource) => <article className={`resource-card ${resource.health}`} key={resource.id}><div className="resource-title"><div><span className={`resource-health ${resource.health}`} /><strong>{resource.label}</strong></div><b>{resource.in_use}/{resource.capacity}</b></div><div className="resource-meter"><span style={{ width: `${Math.min(100, resource.in_use / Math.max(1, resource.capacity) * 100)}%` }} /></div><div className="resource-stats"><span>{resource.waiting} {language === "ru" ? "ожидает" : "waiting"}</span>{resource.requests_per_minute ? <span>{resource.requests_in_window ?? 0}/{resource.requests_per_minute} RPM</span> : null}{resource.requests_per_hour ? <span>{resource.requests_in_hour ?? 0}/{resource.requests_per_hour} RPH</span> : null}{resource.requests_per_day ? <span>{resource.requests_in_day ?? 0}/{resource.requests_per_day} RPD</span> : null}{resource.request_interval_seconds ? <span>{language === "ru" ? "интервал" : "interval"}: {resource.request_interval_seconds}s</span> : null}{resource.tokens_per_minute ? <span>{resource.tokens_in_window ?? 0}/{resource.tokens_per_minute} TPM</span> : null}{resource.tokens_per_hour ? <span>{resource.tokens_in_hour ?? 0}/{resource.tokens_per_hour} TPH</span> : null}{resource.tokens_per_day ? <span>{resource.tokens_in_day ?? 0}/{resource.tokens_per_day} TPD</span> : null}{resource.retry_after_seconds ? <span>{language === "ru" ? "RPM лимит" : "RPM limit"}: {formatDuration(resource.retry_after_seconds)}</span> : null}{resource.token_retry_after_seconds ? <span>{language === "ru" ? "TPM лимит" : "TPM limit"}: {formatDuration(resource.token_retry_after_seconds)}</span> : null}{resource.cooldown_seconds ? <span>{language === "ru" ? "Отключён" : "Cooldown"}: {formatDuration(resource.cooldown_seconds)}</span> : null}</div>{resource.owners[0] ? <p>{resource.owners[0].stage}{resource.owners[0].video_id ? ` · ${resource.owners[0].video_id}` : ""}</p> : <p>{language === "ru" ? "Свободен" : "Idle"}</p>}{resource.last_error ? <small>{resource.last_error}</small> : null}</article>)}</div></section>;
}

function SystemStatus({ health, settings, language, onSelectVideo, onRescan }: { health: Health | null; settings: Settings | null; language: "ru" | "en"; onSelectVideo: (videoId: string) => void; onRescan: () => Promise<void> }) {
  const names: Record<string, string> = { yt_dlp: "yt-dlp", ffmpeg: "ffmpeg", native_transcriber: "Meeting Transcriber", cookies: "YouTube cookies" };
  const [updateState, setUpdateState] = useState<"idle" | "running" | "done">("idle");
  const [restartState, setRestartState] = useState<"idle" | "running">("idle");
  async function updateYtDlp() { setUpdateState("running"); await request("/system/yt-dlp/update", { method: "POST" }); setUpdateState("done"); }
  async function restartBackend() { setRestartState("running"); try { await request("/system/restart", { method: "POST" }); } catch { /* The API may drop the connection while restarting. */ } finally { window.setTimeout(() => setRestartState("idle"), 3000); } }
  if (!health) return <div className="status-section"><div className="page-heading"><div><span className="overline">DIAGNOSTICS</span><h1>{language === "ru" ? "Состояние системы" : "System status"}</h1><p>{language === "ru" ? "Проверяем компоненты в фоне…" : "Checking components in the background…"}</p></div></div></div>;
  const transcriber = health.components.native_transcriber;
  const queueLabels: Record<string, string> = language === "ru" ? { download: "Получение данных", llm: "Языковые модели", tts: "Озвучивание" } : { download: "Data acquisition", llm: "Language models", tts: "Text to speech" };
  const queueDiagnostics = Object.entries(health.queues ?? {}).map(([key, queue]) => ({ key, queue, label: queueLabels[key as "download" | "llm"] ?? key }));
  const queuePanel = queueDiagnostics.length ? <section className="queue-diagnostics"><div className="section-heading"><div><span className="overline">QUEUES</span><h2>{language === "ru" ? "Состояние очередей" : "Queue status"}</h2></div><span className="queue-global-state">{health.queue_paused ? (language === "ru" ? "На паузе" : "Paused") : (language === "ru" ? "Работают" : "Running")}</span></div><div className="queue-diagnostics-grid">{queueDiagnostics.map(({ key, queue, label }) => { const queueState = queue.processing ? (language === "ru" ? "В работе" : "Active") : queue.waiting ? (language === "ru" ? "Ждёт ресурс" : "Waiting for resource") : queue.queued ? (language === "ru" ? "В очереди" : "Queued") : (language === "ru" ? "Нет задач" : "Idle"); return <article className="queue-diagnostic-card" key={key}><div className="queue-diagnostic-title"><h3>{label}</h3><span>{queueState}</span></div><div className="queue-stat-grid"><div><strong>{queue.queued}</strong><small>{language === "ru" ? "в очереди" : "queued"}</small></div><div><strong>{queue.processing}</strong><small>{language === "ru" ? "в работе" : "processing"}</small></div><div><strong>{queue.completed}</strong><small>{language === "ru" ? "готово" : "complete"}</small></div><div><strong>{queue.failed}</strong><small>{language === "ru" ? "ошибки" : "failed"}</small></div><div><strong>{queue.cancelled}</strong><small>{language === "ru" ? "остановлено" : "cancelled"}</small></div></div>{queue.current_stage ? <p className="queue-current-stage">{queue.current_stage}{queue.current_progress !== null ? ` · ${Math.round(queue.current_progress * 100)}%` : ""}{queue.current_video_id ? ` · ${queue.current_video_id}` : ""}</p> : <p className="queue-current-stage">{queue.queued ? (language === "ru" ? "Задачи ожидают запуска" : "Tasks are waiting to start") : (language === "ru" ? "Нет активной задачи" : "No active task")}</p>}</article>; })}</div></section> : null;
  const installGuide = language === "ru" ? <>Установите <a href="https://github.com/pasrom/meeting-transcriber#installation" target="_blank" rel="noreferrer">Meeting Transcriber</a> через Homebrew: <code>brew tap pasrom/meeting-transcriber</code>, затем <code>brew install --cask meeting-transcriber</code>. Откройте приложение в строке меню → Settings → Advanced и включите <strong>Local Automation API</strong>. Подробнее: <a href="https://github.com/pasrom/meeting-transcriber/blob/main/docs/automation-api.md#availability" target="_blank" rel="noreferrer">документация API</a>.</> : <>Install <a href="https://github.com/pasrom/meeting-transcriber#installation" target="_blank" rel="noreferrer">Meeting Transcriber</a> with Homebrew: <code>brew tap pasrom/meeting-transcriber</code>, then <code>brew install --cask meeting-transcriber</code>. Open the menu-bar app → Settings → Advanced and enable <strong>Local Automation API</strong>. See the <a href="https://github.com/pasrom/meeting-transcriber/blob/main/docs/automation-api.md#availability" target="_blank" rel="noreferrer">API documentation</a> for details.</>;
  return <div className="status-section"><div className="page-heading"><div><span className="overline">DIAGNOSTICS</span><h1>{language === "ru" ? "Состояние системы" : "System status"}</h1><p>{health.library}</p></div><div className="page-actions"><button className="secondary-button" onClick={updateYtDlp} disabled={updateState === "running"}>{updateState === "running" ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />}{updateState === "done" ? (language === "ru" ? "Перезапустите приложение" : "Restart the app") : "yt-dlp"}</button><button className="secondary-button" onClick={restartBackend} disabled={restartState === "running"}>{restartState === "running" ? <LoaderCircle size={16} className="spin" /> : <RotateCcw size={16} />}{language === "ru" ? "Перезапустить backend" : "Restart backend"}</button><button className="secondary-button" onClick={onRescan}><RefreshCw size={16} />{language === "ru" ? "Пересканировать" : "Rescan"}</button></div></div>{queuePanel}<ResourcePanel resources={health.resources} language={language} /><PipelineGraph pipeline={health.pipeline} tasks={health.stage_tasks} language={language} onSelectVideo={onSelectVideo} /><div className="health-grid">{Object.entries(health.components).map(([key, component]) => <div className={`health-card ${component.ready ? "ready" : "missing"}`} key={key}><div className="health-icon">{component.ready ? <CheckCircle2 size={22} /> : <AlertCircle size={22} />}</div><div><h3>{names[key] ?? key}</h3><p>{component.ready ? (language === "ru" ? "Готов к работе" : "Ready") : (language === "ru" ? "Требует настройки" : "Needs setup")}</p></div>{component.version ? <code>{component.version}</code> : null}</div>)}</div><section className={`info-card status-info ${transcriber?.ready ? "ready" : "missing"}`}><h2>Meeting Transcriber</h2>{transcriber?.ready ? <><div className="detail-row"><span>{language === "ru" ? "Адрес API" : "API address"}</span><strong>{transcriber.address}</strong></div><div className="detail-row"><span>{language === "ru" ? "Состояние" : "State"}</span><strong>{transcriber.state ?? (language === "ru" ? "Доступен" : "Available")}</strong></div></> : <div className="status-guidance"><p>{language === "ru" ? "Локальный API недоступен." : "The local API is unavailable."}</p><p>{installGuide}</p></div>}</section><section className="info-card status-info"><h2>{language === "ru" ? "Активная конфигурация" : "Active configuration"}</h2><div className="detail-row"><span>{language === "ru" ? "Очередь" : "Queue"}</span><strong>{health.queue_paused ? (language === "ru" ? "На паузе" : "Paused") : (language === "ru" ? "Работает" : "Running")}</strong></div><div className="detail-row"><span>{language === "ru" ? "Провайдер" : "Provider"}</span><strong>{settings?.providers.find((provider) => provider.id === settings.active_provider_id)?.name ?? "—"}</strong></div><div className="detail-row"><span>{language === "ru" ? "Нативный движок" : "Native engine"}</span><strong>{settings?.asr_engine ?? "—"}</strong></div></section></div>;
}
