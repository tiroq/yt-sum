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
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { formatDuration } from "./duration";
import { clipboardPrefillResult } from "./clipboard-prefill";
import { shouldApplySettingsRefresh } from "./settings-refresh";

const API = process.env.NEXT_PUBLIC_YTSUM_API_URL ?? "http://127.0.0.1:8765/api";

type Provider = {
  id: string;
  name: string;
  kind: "ollama" | "openai";
  base_url: string;
  model: string;
  requests_per_minute: number | null;
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
  meeting_transcriber_url: string;
  meeting_transcriber_token_file: string;
  log_retention_days: number;
  providers: Provider[];
  templates: Template[];
};

type SummaryVersion = { provider_id: string; model: string; template_id: string; language: string; mode: string; generated_at: string; file: string };
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
  added_at: string;
  updated_at: string;
  transcript: { language: string; kind: string; engine: string | null; segment_count: number } | null;
  current_summary: SummaryVersion | null;
  summary_stale: boolean;
  summary_versions: SummaryVersion[];
  error: string | null;
};

type VideoDetail = { meta: VideoItem; transcript_markdown: string; summary_markdown: string; folder: string | null };
type Job = { id: string; video_id: string; status: string; stage: string; progress: number; error: string | null; log: string[] };
type Health = { status: string; queue_paused: boolean; library: string; components: Record<string, { ready: boolean; version?: string; engine?: string }> };

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
    summary: "Summary",
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
    summary: "Summary",
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
  const response = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? response.statusText);
  }
  return response.json();
}

function formatDuration(seconds: number | null) {
  if (!seconds) return "";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}` : `${minutes} мин`;
}

function statusLabel(status: string, language: "ru" | "en") {
  const labels: Record<string, [string, string]> = {
    queued: ["В очереди", "Queued"],
    processing: ["Обрабатывается", "Processing"],
    transcript_ready: ["Текст готов", "Transcript ready"],
    complete: ["Готово", "Ready"],
    stale: ["Summary устарело", "Summary is stale"],
    attention: ["Нужно внимание", "Needs attention"],
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
  const [jobs, setJobs] = useState<Job[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const libraryRefreshRevisionRef = useRef(0);
  const [health, setHealth] = useState<Health | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<VideoDetail | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "favorite" | "attention" | "archived" | "playlist">("all");
  const [view, setView] = useState<"library" | "settings" | "status">("library");
  const [addOpen, setAddOpen] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [links, setLinks] = useState("");
  const [cleanTranscript, setCleanTranscript] = useState(false);
  const [error, setError] = useState("");
  const [online, setOnline] = useState(true);

  const language = settings?.interface_language ?? "ru";
  const t = copy[language];
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

  async function addVideos() {
    const urls = links.split(/\n+/).map((value) => value.trim()).filter(Boolean);
    if (!urls.length) return;
    try {
      const payload = await request<{ existing: string[]; errors: { error: string }[] }>("/videos", { method: "POST", body: JSON.stringify({ urls }) });
      setLinks("");
      setAddOpen(false);
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
    setQueueOpen(true);
    await refresh();
  }

  async function refreshVideo() {
    if (!detail) return;
    await request(`/videos/${detail.meta.video_id}/refresh`, { method: "POST" });
    setQueueOpen(true);
    await refresh();
  }

  async function deleteVideo() {
    if (!detail || !window.confirm(language === "ru" ? "Убрать видео из библиотеки?" : "Remove this video from the library?")) return;
    const deleteFiles = window.confirm(language === "ru" ? "Также удалить локальную папку и все файлы?" : "Also delete the local folder and all files?");
    await request(`/videos/${detail.meta.video_id}?delete_files=${deleteFiles}`, { method: "DELETE" });
    setSelectedId(null);
    setDetail(null);
    await refresh();
  }

  return (
    <main className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="brand-row">
          <div className="brand-mark"><Sparkles size={19} strokeWidth={2.4} /></div>
          <div><div className="brand-name">YT Sum</div><div className="brand-subtitle">local intelligence</div></div>
          <button className="icon-button mobile-only" onClick={() => setSidebarOpen(false)} aria-label="Close" tooltip="Закрыть меню. Фокус остаётся на странице."><X size={18} /></button>
        </div>

        <button className="add-button" onClick={() => setAddOpen(true)}><Plus size={18} />{t.add}</button>

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
          <button className="icon-button mobile-only" onClick={() => setSidebarOpen(true)} aria-label="Menu" tooltip="Открыть меню навигации. Фокус перейдёт в боковую панель."><Menu size={20} /></button>
          <div className="breadcrumb"><span>YT Sum</span><span>/</span><strong>{view === "library" ? detail?.meta.title ?? t.library : view === "settings" ? t.settings : t.status}</strong></div>
          <div className="topbar-actions">
            <div className={`online-pill ${online ? "" : "offline"}`}>{online ? <Wifi size={14} /> : <WifiOff size={14} />}{online ? "Local" : "Offline"}</div>
            <button className="queue-button" onClick={() => setQueueOpen(!queueOpen)}><ListChecks size={17} />{t.queue}{activeJobs.length ? <span>{activeJobs.length}</span> : null}</button>
          </div>
        </header>

        {!online ? <OfflineState message={error || t.offline} onRetry={refresh} language={language} /> : view === "settings" && settings ? (
          <SettingsView settings={settings} setSettings={updateSettings} onSaved={refreshSavedSettings} language={language} />
        ) : view === "status" ? (
          <><SystemStatus health={health} settings={settings} language={language} onRescan={async () => { await request("/library/rescan", { method: "POST" }); await refresh(); }} /><SourceUpdatePanel language={language} /></>
        ) : detail ? (
          <>
            <section className="video-hero">
              <div className="hero-thumb"><img src={detail.meta.thumbnail_file ? `${API}/videos/${detail.meta.video_id}/thumbnail` : `https://i.ytimg.com/vi/${detail.meta.video_id}/hqdefault.jpg`} alt="" /><span className="tooltip-wrap"><a href={detail.meta.source_url} target="_blank" rel="noreferrer" aria-label="Open video" aria-describedby="open-video-tooltip"><Play size={20} fill="currentColor" /></a><span className="tooltip" id="open-video-tooltip" role="tooltip">Открыть видео на YouTube. Откроется новая вкладка.</span></span></div>
              <div className="hero-copy"><div className="eyebrow"><span className={`status-badge ${detail.meta.status}`}>{statusLabel(detail.meta.status, language)}</span>{detail.meta.transcript ? <span><Languages size={13} />{detail.meta.transcript.language.toUpperCase()} · {detail.meta.transcript.kind}</span> : null}</div><h1>{detail.meta.title}</h1><p>{detail.meta.channel} {detail.meta.published_at ? `· ${detail.meta.published_at}` : ""} {detail.meta.duration_seconds !== null ? `· ${formatDuration(detail.meta.duration_seconds)}` : ""}</p><div className="tag-row">{detail.meta.tags.map((tagName) => <span key={tagName}><Tag size={11} />{tagName}</span>)}</div></div>
              <div className="hero-actions"><IconButton className={`icon-button ${detail.meta.favorite ? "favorite" : ""}`} onClick={toggleFavorite} aria-label={detail.meta.favorite ? "Remove from favorites" : "Add to favorites"} tooltip={detail.meta.favorite ? "Убрать из избранного. Видео исчезнет из фильтра «Избранное»." : "Добавить в избранное. Видео появится в фильтре «Избранное»."}><Heart size={19} fill={detail.meta.favorite ? "currentColor" : "none"} /></IconButton><IconButton className="icon-button" onClick={editTags} aria-label="Edit tags" tooltip="Изменить теги. Сохранённые теги будут заменены."><Tag size={18} /></IconButton><IconButton className="icon-button" onClick={refreshVideo} aria-label="Refresh" tooltip="Обновить видео. Сбор данных будет поставлен в очередь."><RefreshCw size={18} /></IconButton><IconButton className="icon-button danger-hover" onClick={deleteVideo} aria-label="Delete" tooltip="Удалить видео. Затем можно удалить и локальные файлы."><Trash2 size={18} /></IconButton></div>
            </section>

            <nav className="tabs">
              <button className={tab === "summary" ? "active" : ""} onClick={() => setTab("summary")}><Sparkles size={16} />{t.summary}</button>
              <button className={tab === "transcript" ? "active" : ""} onClick={() => setTab("transcript")}><FileText size={16} />{t.transcript}</button>
              <button className={tab === "details" ? "active" : ""} onClick={() => setTab("details")}><SlidersHorizontal size={16} />{t.details}</button>
            </nav>

            <section className="content-scroll">
              {tab === "summary" ? <MarkdownPanel markdown={detail.summary_markdown} empty={language === "ru" ? "Summary ещё не создано." : "Summary has not been created yet."} action={<button className="secondary-button" onClick={resummarize}><RotateCcw size={16} />{language === "ru" ? "Создать заново" : "Regenerate"}</button>} /> : null}
              {tab === "transcript" ? <TranscriptPanel markdown={detail.transcript_markdown} clean={cleanTranscript} setClean={setCleanTranscript} language={language} /> : null}
              {tab === "details" ? <DetailsPanel detail={detail} jobs={jobs.filter((job) => job.video_id === detail.meta.video_id)} language={language} /> : null}
            </section>
          </>
        ) : (
          <EmptyState onAdd={() => setAddOpen(true)} title={t.emptyTitle} body={t.emptyBody} />
        )}
      </section>

      {addOpen ? <AddDialog links={links} setLinks={setLinks} onClose={() => setAddOpen(false)} onAdd={addVideos} language={language} /> : null}
      {queueOpen ? <QueuePanel jobs={jobs} paused={health?.queue_paused ?? false} close={() => setQueueOpen(false)} refresh={refresh} language={language} /> : null}
      {error && online ? <div className="toast"><AlertCircle size={18} /><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error" tooltip="Закрыть сообщение об ошибке. Выполненное действие не отменяется."><X size={16} /></IconButton></div> : null}
      {notice ? <div className="toast success" role="status"><CheckCircle2 size={18} /><span>{notice}</span><IconButton onClick={() => setNotice("")} aria-label="Dismiss notification" tooltip="Закрыть уведомление."><X size={16} /></IconButton></div> : null}
    </main>
  );
}

function MarkdownPanel({ markdown, empty, action }: { markdown: string; empty: string; action: React.ReactNode }) {
  return <article className="document-card"><div className="document-toolbar"><div><span className="overline">AI NOTES</span><h2>Summary</h2></div>{action}</div>{markdown ? <div className="markdown"><ReactMarkdown components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer">{children}</a> }}>{markdown.replace(/^---\n[\s\S]*?\n---\n/, "")}</ReactMarkdown></div> : <div className="empty-inline"><Sparkles size={28} /><p>{empty}</p></div>}</article>;
}

function TranscriptPanel({ markdown, clean, setClean, language }: { markdown: string; clean: boolean; setClean: (value: boolean) => void; language: "ru" | "en" }) {
  const plain = markdown.replace(/^---\n[\s\S]*?\n---\n/, "").replace(/^#.*$/m, "").replace(/\[([^\]]+)\]\([^)]+\)\s*/g, "").replace(/\*\*/g, "").trim();
  return <article className="document-card transcript-document"><div className="document-toolbar"><div><span className="overline">SOURCE</span><h2>{language === "ru" ? "Полная транскрипция" : "Full transcript"}</h2></div><label className="switch-label"><input id="clean-transcript" name="clean-transcript" type="checkbox" checked={clean} onChange={(event) => setClean(event.target.checked)} /><span />{language === "ru" ? "Чистый текст" : "Clean text"}</label></div>{markdown ? clean ? <div className="plain-transcript">{plain}</div> : <div className="markdown transcript-markdown"><ReactMarkdown components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer">{children}</a> }}>{markdown.replace(/^---\n[\s\S]*?\n---\n/, "")}</ReactMarkdown></div> : <div className="empty-inline"><FileText size={28} /><p>{language === "ru" ? "Транскрипция ещё не готова." : "Transcript is not ready yet."}</p></div>}</article>;
}

function DetailsPanel({ detail, jobs, language }: { detail: VideoDetail; jobs: Job[]; language: "ru" | "en" }) {
  const rows = [
    ["YouTube ID", detail.meta.video_id],
    [language === "ru" ? "Папка" : "Folder", detail.folder ?? "—"],
    [language === "ru" ? "Язык текста" : "Transcript language", detail.meta.transcript?.language ?? "—"],
    [language === "ru" ? "Источник текста" : "Transcript source", detail.meta.transcript?.kind ?? "—"],
    [language === "ru" ? "Модель summary" : "Summary model", detail.meta.current_summary?.model ?? "—"],
    [language === "ru" ? "Версий summary" : "Summary versions", String(detail.meta.summary_versions.length + (detail.meta.current_summary ? 1 : 0))],
  ];
  return <div className="details-grid"><section className="info-card"><span className="overline">FILE-FIRST</span><h2>{language === "ru" ? "Данные видео" : "Video data"}</h2>{rows.map(([label, value]) => <div className="detail-row" key={label}><span>{label}</span><strong title={value}>{value}</strong></div>)}<button className="secondary-button" onClick={onOpenFolder} disabled={!detail.folder}><FolderOpen size={16} />{language === "ru" ? "Открыть папку артефактов" : "Open artifacts folder"}</button></section><section className="info-card"><span className="overline">PROCESSING</span><h2>{language === "ru" ? "История обработки" : "Processing history"}</h2>{jobs.length ? jobs.map((job) => <details className="job-history" key={job.id}><summary><div className={`job-state ${job.status}`}><Clock3 size={15} /></div><div><strong>{job.stage}</strong><p>{job.error || `${Math.round(job.progress * 100)}%`}</p></div>{["complete", "attention"].includes(job.status) ? <button className="mini-button danger-hover job-history-delete" onClick={(event) => { event.preventDefault(); event.stopPropagation(); onDeleteJob(job); }} aria-label={language === "ru" ? "Удалить запись истории" : "Remove history entry"} title={language === "ru" ? "Удалить запись истории" : "Remove history entry"}><X size={14} /></button> : null}</summary>{job.log.length ? <div className="job-log"><button className="text-button" onClick={() => { void navigator.clipboard.writeText(job.log.join("\n")); }}><FileText size={13} />{language === "ru" ? "Копировать лог" : "Copy log"}</button><pre>{job.log.join("\n")}</pre></div> : null}</details>) : <p className="muted">{language === "ru" ? "Задач пока нет." : "No jobs yet."}</p>}</section></div>;
}

function EmptyState({ onAdd, title, body }: { onAdd: () => void; title: string; body: string }) {
  return <div className="empty-state"><div className="empty-orbit"><Video size={34} /><span /><span /></div><h1>{title}</h1><p>{body}</p><button className="primary-button" onClick={onAdd}><Plus size={17} />Добавить ссылку</button><div className="feature-hints"><span><CheckCircle2 size={15} />Markdown first</span><span><CheckCircle2 size={15} />Local models</span><span><CheckCircle2 size={15} />Slow & respectful</span></div></div>;
}

function OfflineState({ message, onRetry, language }: { message: string; onRetry: () => void; language: "ru" | "en" }) {
  return <div className="empty-state offline-state"><div className="empty-orbit danger"><WifiOff size={32} /></div><h1>{language === "ru" ? "Сервис не отвечает" : "Service is unavailable"}</h1><p>{message}</p><button className="primary-button" onClick={onRetry}><RefreshCw size={17} />{language === "ru" ? "Проверить снова" : "Try again"}</button><code>./scripts/dev.sh</code></div>;
}

function AddDialog({ links, setLinks, onClose, onAdd, language }: { links: string; setLinks: (value: string) => void; onClose: () => void; onAdd: () => void; language: "ru" | "en" }) {
  const [clipboardMessage, setClipboardMessage] = useState("");
  const linksRef = useRef(links);

  useEffect(() => {
    linksRef.current = links;
  }, [links]);

  useEffect(() => {
    let active = true;
    async function prefillFromClipboard() {
      if (!navigator.clipboard?.readText) {
        setClipboardMessage(language === "ru" ? "Не удалось прочитать буфер обмена. Вставьте ссылку вручную." : "Could not read the clipboard. Paste the link manually.");
        return;
      }
      try {
        const result = clipboardPrefillResult(linksRef.current, await navigator.clipboard.readText());
        if (!active || result.kind === "ignored") return;
        if (result.kind === "prefilled") {
          setLinks(result.value);
          setClipboardMessage(language === "ru" ? "Ссылка YouTube добавлена из буфера обмена." : "YouTube link added from the clipboard.");
        }
      } catch (failure) {
        const result = clipboardPrefillResult(links, "", failure);
        if (!active) return;
        setClipboardMessage(result.kind === "permission-denied"
          ? (language === "ru" ? "Нет доступа к буферу обмена. Вставьте ссылку вручную." : "Clipboard access was denied. Paste the link manually.")
          : (language === "ru" ? "Не удалось прочитать буфер обмена. Вставьте ссылку вручную." : "Could not read the clipboard. Paste the link manually."));
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

  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="add-dialog-title"><div className="modal-heading"><div><span className="overline">YOUTUBE</span><h2 id="add-dialog-title">{language === "ru" ? "Добавить в библиотеку" : "Add to library"}</h2></div><IconButton className="icon-button" onClick={onClose} aria-label="Close" tooltip="Закрыть окно. Несохранённые ссылки будут потеряны."><X size={18} /></IconButton></div><p>{language === "ru" ? "Вставьте одну или несколько ссылок — по одной на строку." : "Paste one or more links, one per line."}</p><textarea id="youtube-links" name="youtube-links" value={links} onChange={(event) => setLinks(event.target.value)} placeholder="https://www.youtube.com/watch?v=…" rows={7} aria-label={language === "ru" ? "Ссылки YouTube" : "YouTube links"} />{clipboardMessage ? <p className="clipboard-status" role="status">{clipboardMessage}</p> : null}<div className="modal-note"><Clock3 size={16} /><span>{language === "ru" ? "Видео обрабатываются по одному с паузами 30–90 секунд." : "Videos are processed one at a time with 30–90 second pauses."}</span></div><div className="modal-actions"><button className="ghost-button" onClick={onClose}>{language === "ru" ? "Отмена" : "Cancel"}</button><button className="primary-button" onClick={onAdd} disabled={!links.trim()}><Plus size={17} />{language === "ru" ? "Добавить в очередь" : "Add to queue"}</button></div></section></div>;
}

function QueuePanel({ jobs, paused, close, refresh, language }: { jobs: Job[]; paused: boolean; close: () => void; refresh: () => Promise<void>; language: "ru" | "en" }) {
  async function queueAction(path: string) { await request(path, { method: "POST" }); await refresh(); }
  async function moveJob(job: Job, delta: number) {
    const queued = jobs.filter((item) => item.status === "queued");
    const index = queued.findIndex((item) => item.id === job.id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= queued.length) return;
    [queued[index], queued[target]] = [queued[target], queued[index]];
    await request("/jobs/reorder", { method: "POST", body: JSON.stringify({ job_ids: queued.map((item) => item.id) }) });
    await refresh();
  }
  return <aside className="queue-panel"><div className="queue-heading"><div><span className="overline">BACKGROUND</span><h2>{language === "ru" ? "Очередь обработки" : "Processing queue"}</h2></div><button className="icon-button" onClick={close}><X size={18} /></button></div><button className="queue-control" onClick={() => queueAction(paused ? "/jobs/resume" : "/jobs/pause")}>{paused ? <Play size={16} /> : <Pause size={16} />}{paused ? (language === "ru" ? "Продолжить" : "Resume") : (language === "ru" ? "Пауза" : "Pause")}</button><div className="queue-items">{jobs.length ? jobs.map((job) => <div className="queue-item" key={job.id}><div className="queue-item-top"><div className={`job-icon ${job.status}`}>{job.status === "processing" ? <LoaderCircle size={16} className="spin" /> : job.status === "complete" ? <CheckCircle2 size={16} /> : job.status === "attention" ? <AlertCircle size={16} /> : <Clock3 size={16} />}</div><div><strong>{job.stage}</strong><small>{job.video_id}</small></div>{job.status === "queued" ? <div className="reorder-buttons"><button className="mini-button" onClick={() => moveJob(job, -1)} aria-label="Move up"><ChevronUp size={13} /></button><button className="mini-button" onClick={() => moveJob(job, 1)} aria-label="Move down"><ChevronDown size={13} /></button></div> : null}<button className="mini-button" onClick={() => queueAction(job.status === "attention" ? `/jobs/${job.id}/retry` : `/jobs/${job.id}/cancel`)}>{job.status === "attention" ? <RotateCcw size={14} /> : <Square size={13} />}</button></div><div className="progress-track"><span style={{ width: `${job.progress * 100}%` }} /></div>{job.error ? <p className="job-error">{job.error}</p> : null}</div>) : <div className="queue-empty"><CheckCircle2 size={24} /><p>{language === "ru" ? "Очередь пуста" : "Queue is empty"}</p></div>}</div></aside>;
}

function SettingsView({ settings, setSettings, onSaved, language }: { settings: Settings; setSettings: (value: Settings) => void; onSaved: () => Promise<void>; language: "ru" | "en" }) {
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [secret, setSecretValue] = useState<Record<string, string>>({});
  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => setSettings({ ...settings, [key]: value });
  const updateProvider = (id: string, patch: Partial<Provider>) => update("providers", settings.providers.map((provider) => provider.id === id ? { ...provider, ...patch } : provider));
  const updateTemplate = (id: string, patch: Partial<Template>) => update("templates", settings.templates.map((template) => template.id === id ? { ...template, ...patch } : template));

  async function save() { setSaving(true); try { await request("/settings", { method: "PUT", body: JSON.stringify(settings) }); for (const [id, apiKey] of Object.entries(secret)) if (apiKey) await request(`/providers/${id}/secret`, { method: "POST", body: JSON.stringify({ api_key: apiKey }) }); setSecretValue({}); await onSaved(); } finally { setSaving(false); } }
  async function discover(provider: Provider) { const payload = await request<{ items: string[] }>(`/providers/${provider.id}/models`, { method: "POST" }); setModels({ ...models, [provider.id]: payload.items }); }
  function addProvider() { const id = `provider-${Date.now()}`; update("providers", [...settings.providers, { id, name: "New endpoint", kind: "openai", base_url: "http://127.0.0.1:8000/v1", model: "", requests_per_minute: null, temperature: 0, max_output_tokens: 2048, remote: false, remote_confirmed: true, has_api_key: false }]); }
  function addTemplate() { const id = `template-${Date.now()}`; update("templates", [...settings.templates, { id, name_ru: "Новый шаблон", name_en: "New template", prompt: "Create a faithful Markdown summary in {language}.", builtin: false }]); update("summary_template_id", id); }

  return <div className="settings-page"><div className="page-heading"><div><span className="overline">LOCAL-FIRST</span><h1>{language === "ru" ? "Настройки" : "Settings"}</h1><p>{language === "ru" ? "Всё хранится на этом Mac. Секреты — только в Связке ключей." : "Everything stays on this Mac. Secrets are stored only in Keychain."}</p></div><button className="primary-button" onClick={save} disabled={saving}>{saving ? <LoaderCircle size={16} className="spin" /> : <CheckCircle2 size={16} />}{language === "ru" ? "Сохранить" : "Save"}</button></div>
    <div className="settings-layout">
      <section className="settings-card"><div className="settings-card-title"><FolderOpen size={19} /><div><h2>{language === "ru" ? "Библиотека и языки" : "Library and languages"}</h2><p>Markdown + JSON</p></div></div><label className="field full"><span>{language === "ru" ? "Папка библиотеки" : "Library folder"}</span><input id="library-dir" name="library-dir" value={settings.library_dir} onChange={(e) => update("library_dir", e.target.value)} /></label><div className="field-grid"><label className="field"><span>{language === "ru" ? "Основной текст" : "Primary transcript"}</span><input value={settings.primary_language} onChange={(e) => update("primary_language", e.target.value)} /></label><label className="field"><span>{language === "ru" ? "Запасной текст" : "Fallback transcript"}</span><input value={settings.secondary_language} onChange={(e) => update("secondary_language", e.target.value)} /></label><label className="field"><span>{language === "ru" ? "Язык summary" : "Summary language"}</span><input value={settings.summary_language} onChange={(e) => update("summary_language", e.target.value)} /></label><label className="field"><span>{language === "ru" ? "Интерфейс" : "Interface"}</span><select value={settings.interface_language} onChange={(e) => update("interface_language", e.target.value as "ru" | "en")}><option value="ru">Русский</option><option value="en">English</option></select></label></div></section>

      <section className="settings-card"><div className="settings-card-title"><Clock3 size={19} /><div><h2>{language === "ru" ? "Бережная загрузка" : "Respectful downloading"}</h2><p>yt-dlp</p></div></div><div className="field-grid"><label className="field"><span>{language === "ru" ? "Минимальная пауза, сек" : "Minimum delay, sec"}</span><input id="min-delay" name="min-delay" type="number" value={settings.min_download_delay_seconds} onChange={(e) => update("min_download_delay_seconds", Number(e.target.value))} /></label><label className="field"><span>{language === "ru" ? "Максимальная пауза, сек" : "Maximum delay, sec"}</span><input id="max-delay" name="max-delay" type="number" value={settings.max_download_delay_seconds} onChange={(e) => update("max_download_delay_seconds", Number(e.target.value))} /></label></div><label className="field full"><span>cookies.txt</span><input id="cookie-file" name="cookie-file" value={settings.cookie_file} onChange={(e) => update("cookie_file", e.target.value)} placeholder="~/Downloads/cookies.txt" /></label><label className="field full"><span>{language === "ru" ? "Cookies браузера" : "Browser cookies"}</span><select value={settings.cookie_browser} onChange={(e) => update("cookie_browser", e.target.value)}><option value="">{language === "ru" ? "Не использовать" : "Disabled"}</option><option value="chrome">Chrome</option><option value="safari">Safari</option><option value="firefox">Firefox</option></select></label></section>

      <section className="settings-card wide"><div className="settings-card-title"><Sparkles size={19} /><div><h2>{language === "ru" ? "Модели summary" : "Summary models"}</h2><p>Ollama · OpenAI-compatible</p></div><button className="text-button" onClick={addProvider}><Plus size={15} />Endpoint</button></div><div className="provider-grid">{settings.providers.map((provider) => <div className={`provider-card ${settings.active_provider_id === provider.id ? "active" : ""}`} key={provider.id}><div className="provider-top"><button className="provider-radio" onClick={() => update("active_provider_id", provider.id)}><span />{settings.active_provider_id === provider.id ? (language === "ru" ? "По умолчанию" : "Default") : (language === "ru" ? "Выбрать" : "Select")}</button><select value={provider.kind} onChange={(e) => updateProvider(provider.id, { kind: e.target.value as "ollama" | "openai" })}><option value="ollama">Ollama</option><option value="openai">OpenAI-compatible</option></select></div><input className="provider-name" value={provider.name} onChange={(e) => updateProvider(provider.id, { name: e.target.value })} /><label className="field full"><span>Endpoint</span><input value={provider.base_url} onChange={(e) => updateProvider(provider.id, { base_url: e.target.value })} /></label><div className="model-row"><label className="field"><span>{language === "ru" ? "Модель" : "Model"}</span><input list={`models-${provider.id}`} value={provider.model} onChange={(e) => updateProvider(provider.id, { model: e.target.value })} /><datalist id={`models-${provider.id}`}>{models[provider.id]?.map((name) => <option value={name} key={name} />)}</datalist></label><button className="discover-button" onClick={() => discover(provider)} aria-label="Discover models"><RefreshCw size={15} /></button></div><div className="field-grid"><label className="field"><span>RPM</span><input type="number" placeholder="∞" value={provider.requests_per_minute ?? ""} onChange={(e) => updateProvider(provider.id, { requests_per_minute: e.target.value ? Number(e.target.value) : null })} /></label><label className="field"><span>Temperature</span><input type="number" step="0.1" value={provider.temperature} onChange={(e) => updateProvider(provider.id, { temperature: Number(e.target.value) })} /></label></div><label className="field full"><span>API key · Keychain</span><input type="password" value={secret[provider.id] ?? ""} onChange={(e) => setSecretValue({ ...secret, [provider.id]: e.target.value })} placeholder={provider.has_api_key ? "••••••••••••" : "Optional"} /></label><label className="check-row"><input type="checkbox" checked={provider.remote} onChange={(e) => updateProvider(provider.id, { remote: e.target.checked, remote_confirmed: !e.target.checked })} />{language === "ru" ? "Это удалённый endpoint" : "This is a remote endpoint"}</label>{provider.remote ? <label className="check-row privacy-check"><input type="checkbox" checked={provider.remote_confirmed} onChange={(e) => updateProvider(provider.id, { remote_confirmed: e.target.checked })} />{language === "ru" ? "Разрешаю отправку текста этому провайдеру" : "Allow transcript upload to this provider"}</label> : null}</div>)}</div></section>

      <section className="settings-card"><div className="settings-card-title"><FileText size={19} /><div><h2>{language === "ru" ? "Суммаризация" : "Summarization"}</h2><p>Full coverage by default</p></div></div><label className="field full"><span>{language === "ru" ? "Режим" : "Mode"}</span><select id="summary-mode" name="summary-mode" value={settings.summary_mode} onChange={(e) => update("summary_mode", e.target.value as "complete" | "cluster")}><option value="complete">{language === "ru" ? "Полное покрытие (map-reduce)" : "Complete coverage (map-reduce)"}</option><option value="cluster">{language === "ru" ? "Быстрый кластерный (lossy)" : "Fast clustering (lossy)"}</option></select></label><label className="field full"><span>{language === "ru" ? "Шаблон" : "Template"}</span><select id="summary-template" name="summary-template" value={settings.summary_template_id} onChange={(e) => update("summary_template_id", e.target.value)}>{settings.templates.map((template) => <option key={template.id} value={template.id}>{language === "ru" ? template.name_ru : template.name_en}</option>)}</select></label><label className="field full"><span>{language === "ru" ? "Размер фрагмента, символов" : "Chunk size, characters"}</span><input id="chunk-chars" name="chunk-chars" type="number" value={settings.chunk_characters} onChange={(e) => update("chunk_characters", Number(e.target.value))} /></label></section>

      <section className="settings-card"><div className="settings-card-title"><Languages size={19} /><div><h2>{language === "ru" ? "Распознавание аудио" : "Audio transcription"}</h2><p>Meeting Transcriber · CoreML</p></div></div><label className="field full"><span>{language === "ru" ? "Движок" : "Engine"}</span><select id="asr-engine" name="asr-engine" value={settings.asr_engine} onChange={(e) => update("asr_engine", e.target.value as "whisperkit" | "parakeet")}><option value="whisperkit">WhisperKit</option><option value="parakeet">Parakeet TDT v3</option></select></label><label className="field full"><span>Automation API</span><input id="transcriber-url" name="transcriber-url" value={settings.meeting_transcriber_url} onChange={(e) => update("meeting_transcriber_url", e.target.value)} /></label><label className="check-row"><input type="checkbox" checked={settings.diarization_enabled} onChange={(e) => update("diarization_enabled", e.target.checked)} />{language === "ru" ? "Разделять спикеров" : "Speaker diarization"}</label><label className="check-row"><input type="checkbox" checked={settings.keep_audio} onChange={(e) => update("keep_audio", e.target.checked)} />{language === "ru" ? "Сохранять аудио" : "Keep audio files"}</label></section>

      <section className="settings-card wide"><div className="settings-card-title"><FileText size={19} /><div><h2>{language === "ru" ? "Шаблоны summary" : "Summary templates"}</h2><p>{language === "ru" ? "Встроенные и пользовательские инструкции" : "Built-in and custom instructions"}</p></div><button className="text-button" onClick={addTemplate}><Plus size={15} />{language === "ru" ? "Шаблон" : "Template"}</button></div><div className="template-grid">{settings.templates.map((template) => <div className={`template-card ${settings.summary_template_id === template.id ? "active" : ""}`} key={template.id}><div className="template-title-row"><button className="provider-radio" onClick={() => update("summary_template_id", template.id)}><span />{settings.summary_template_id === template.id ? (language === "ru" ? "Активный" : "Active") : (language === "ru" ? "Выбрать" : "Select")}</button>{!template.builtin ? <button className="mini-button danger-hover" onClick={() => update("templates", settings.templates.filter((item) => item.id !== template.id))} aria-label="Delete template"><Trash2 size={13} /></button> : null}</div><div className="field-grid"><label className="field"><span>RU</span><input value={template.name_ru} onChange={(e) => updateTemplate(template.id, { name_ru: e.target.value })} disabled={template.builtin} /></label><label className="field"><span>EN</span><input value={template.name_en} onChange={(e) => updateTemplate(template.id, { name_en: e.target.value })} disabled={template.builtin} /></label></div><label className="field full"><span>Prompt</span><textarea value={template.prompt} onChange={(e) => updateTemplate(template.id, { prompt: e.target.value })} disabled={template.builtin} rows={4} /></label></div>)}</div></section>
    </div>
  </div>;
}

function SystemStatus({ health, settings, language, onRescan }: { health: Health; settings: Settings | null; language: "ru" | "en"; onRescan: () => Promise<void> }) {
  const names: Record<string, string> = { yt_dlp: "yt-dlp", ffmpeg: "ffmpeg", native_transcriber: "Meeting Transcriber", cookies: "YouTube cookies" };
  const [updateState, setUpdateState] = useState<"idle" | "running" | "done">("idle");
  async function updateYtDlp() { setUpdateState("running"); await request("/system/yt-dlp/update", { method: "POST" }); setUpdateState("done"); }
  if (!health) return <div className="status-page"><div className="page-heading"><div><span className="overline">DIAGNOSTICS</span><h1>{language === "ru" ? "Состояние системы" : "System status"}</h1><p>{language === "ru" ? "Проверяем компоненты в фоне…" : "Checking components in the background…"}</p></div></div></div>;
  const transcriber = health.components.native_transcriber;
  const installGuide = language === "ru" ? <>Установите <a href="https://github.com/pasrom/meeting-transcriber#installation" target="_blank" rel="noreferrer">Meeting Transcriber</a> через Homebrew: <code>brew tap pasrom/meeting-transcriber</code>, затем <code>brew install --cask meeting-transcriber</code>. Откройте приложение в строке меню → Settings → Advanced и включите <strong>Local Automation API</strong>. Подробнее: <a href="https://github.com/pasrom/meeting-transcriber/blob/main/docs/automation-api.md#availability" target="_blank" rel="noreferrer">документация API</a>.</> : <>Install <a href="https://github.com/pasrom/meeting-transcriber#installation" target="_blank" rel="noreferrer">Meeting Transcriber</a> with Homebrew: <code>brew tap pasrom/meeting-transcriber</code>, then <code>brew install --cask meeting-transcriber</code>. Open the menu-bar app → Settings → Advanced and enable <strong>Local Automation API</strong>. See the <a href="https://github.com/pasrom/meeting-transcriber/blob/main/docs/automation-api.md#availability" target="_blank" rel="noreferrer">API documentation</a> for details.</>;
  return <div className="status-page"><div className="page-heading"><div><span className="overline">DIAGNOSTICS</span><h1>{language === "ru" ? "Состояние системы" : "System status"}</h1><p>{health.library}</p></div><div className="page-actions"><button className="secondary-button" onClick={updateYtDlp} disabled={updateState === "running"}>{updateState === "running" ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />}{updateState === "done" ? (language === "ru" ? "Перезапустите приложение" : "Restart the app") : "yt-dlp"}</button><button className="secondary-button" onClick={onRescan}><RefreshCw size={16} />{language === "ru" ? "Пересканировать" : "Rescan"}</button></div></div><div className="health-grid">{Object.entries(health.components).map(([key, component]) => <div className={`health-card ${component.ready ? "ready" : "missing"}`} key={key}><div className="health-icon">{component.ready ? <CheckCircle2 size={22} /> : <AlertCircle size={22} />}</div><div><h3>{names[key] ?? key}</h3><p>{component.ready ? (language === "ru" ? "Готов к работе" : "Ready") : (language === "ru" ? "Требует настройки" : "Needs setup")}</p></div>{component.version ? <code>{component.version}</code> : null}</div>)}</div><section className={`info-card status-info ${transcriber?.ready ? "ready" : "missing"}`}><h2>Meeting Transcriber</h2>{transcriber?.ready ? <><div className="detail-row"><span>{language === "ru" ? "Адрес API" : "API address"}</span><strong>{transcriber.address}</strong></div><div className="detail-row"><span>{language === "ru" ? "Состояние" : "State"}</span><strong>{transcriber.state ?? (language === "ru" ? "Доступен" : "Available")}</strong></div></> : <div className="status-guidance"><p>{language === "ru" ? "Локальный API недоступен." : "The local API is unavailable."}</p><p>{installGuide}</p></div>}</section><section className="info-card status-info"><h2>{language === "ru" ? "Активная конфигурация" : "Active configuration"}</h2><div className="detail-row"><span>{language === "ru" ? "Очередь" : "Queue"}</span><strong>{health.queue_paused ? (language === "ru" ? "На паузе" : "Paused") : (language === "ru" ? "Работает" : "Running")}</strong></div><div className="detail-row"><span>{language === "ru" ? "Провайдер" : "Provider"}</span><strong>{settings?.providers.find((provider) => provider.id === settings.active_provider_id)?.name ?? "—"}</strong></div><div className="detail-row"><span>{language === "ru" ? "Нативный движок" : "Native engine"}</span><strong>{settings?.asr_engine ?? "—"}</strong></div></section></div>;
}
