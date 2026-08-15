from __future__ import annotations

import json
import re
import shutil
import sqlite3
import unicodedata
import uuid
import time
from pathlib import Path
from threading import RLock
from typing import Any

from .models import (
    JobRecord,
    PipelineEventRecord,
    PlaylistMeta,
    PlaylistRef,
    PromptArtifact,
    StageTaskRecord,
    VideoDetail,
    VideoMeta,
    WorkflowRecord,
    utc_now,
)


INVALID_FILENAME = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def safe_folder_name(title: str, published_at: str | None, video_id: str) -> str:
    date = (published_at or "undated")[:10]
    normalized = unicodedata.normalize("NFC", title).strip()
    normalized = INVALID_FILENAME.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .") or "Untitled video"
    normalized = normalized[:100].rstrip()
    return f"{date} {normalized} [{video_id}]"


class LibraryStorage:
    def __init__(self, library_dir: Path) -> None:
        self.library_dir = library_dir.expanduser().resolve()
        self.internal_dir = self.library_dir / ".yt-sum"
        self.logs_dir = self.internal_dir / "logs"
        self.work_dir = self.internal_dir / "work"
        self.db_path = self.internal_dir / "index.sqlite3"
        self._lock = RLock()
        self._prepare_directories()
        self._initialize_database()

    def _prepare_directories(self) -> None:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.internal_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        self.work_dir.mkdir(exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize_database(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                title TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                duration_seconds INTEGER,
                thumbnail_file TEXT,
                thumbnail_url TEXT,
                folder TEXT,
                status TEXT NOT NULL,
                favorite INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                tags_json TEXT NOT NULL DEFAULT '[]',
                transcript_language TEXT,
                transcript_kind TEXT,
                added_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_videos_status_updated ON videos(status, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_videos_favorite_updated ON videos(favorite, updated_at)",
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                position INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT,
                log_json TEXT NOT NULL DEFAULT '[]',
                stage_log_json TEXT NOT NULL DEFAULT '[]',
                requests_planned INTEGER NOT NULL DEFAULT 0,
                requests_completed INTEGER NOT NULL DEFAULT 0,
                summary_source TEXT,
                provider_id TEXT,
                provider_name TEXT,
                model TEXT,
                overrides_json TEXT NOT NULL DEFAULT '{}'
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_position ON jobs(status, position)",
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                settings_snapshot_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                paused_at TEXT,
                completed_at TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_workflows_video_updated ON workflows(video_id, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_workflows_status_priority ON workflows(status, priority, created_at)",
            """
            CREATE TABLE IF NOT EXISTS stage_tasks (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
                video_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                state TEXT NOT NULL,
                required INTEGER NOT NULL DEFAULT 1,
                progress REAL NOT NULL DEFAULT 0,
                waiting_for_json TEXT,
                resource_id TEXT,
                attempt INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                UNIQUE(workflow_id, stage)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_stage_tasks_live ON stage_tasks(state, stage)",
            "CREATE INDEX IF NOT EXISTS idx_stage_tasks_workflow ON stage_tasks(workflow_id, created_at)",
            """
            CREATE TABLE IF NOT EXISTS stage_attempts (
                id TEXT PRIMARY KEY,
                stage_task_id TEXT NOT NULL REFERENCES stage_tasks(id) ON DELETE CASCADE,
                workflow_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                state TEXT NOT NULL,
                resource_id TEXT,
                worker_id TEXT,
                started_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_stage_attempts_task ON stage_attempts(stage_task_id, ordinal)",
            """
            CREATE TABLE IF NOT EXISTS resource_leases (
                id TEXT PRIMARY KEY,
                resource_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL REFERENCES stage_attempts(id) ON DELETE CASCADE,
                workflow_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                released_at TEXT
            )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_resource_live_attempt ON resource_leases(attempt_id) WHERE released_at IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_resource_live_resource ON resource_leases(resource_id, released_at)",
            """
            CREATE TABLE IF NOT EXISTS pipeline_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                stage_task_id TEXT,
                video_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                event TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT,
                message TEXT NOT NULL DEFAULT '',
                resource_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pipeline_events_workflow_sequence ON pipeline_events(workflow_id, sequence)",
            "CREATE VIRTUAL TABLE IF NOT EXISTS video_search USING fts5(video_id UNINDEXED, title, channel, tags, transcript, summary)",
        ]
        with self._connect() as connection:
            for statement in statements:
                connection.execute(statement)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(videos)")}
            if "archived" not in columns:
                connection.execute("ALTER TABLE videos ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_videos_archived_updated ON videos(archived, updated_at)")
            if "playlists_json" not in columns:
                connection.execute("ALTER TABLE videos ADD COLUMN playlists_json TEXT NOT NULL DEFAULT '[]'")
            existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            migrations = {
                "stage_log_json": "TEXT NOT NULL DEFAULT '[]'",
                "requests_planned": "INTEGER NOT NULL DEFAULT 0",
                "requests_completed": "INTEGER NOT NULL DEFAULT 0",
                "summary_source": "TEXT",
                "provider_id": "TEXT",
                "provider_name": "TEXT",
                "model": "TEXT",
                "workflow_id": "TEXT NOT NULL DEFAULT ''",
                "execution_state": "TEXT NOT NULL DEFAULT 'queued'",
                "waiting_for_json": "TEXT",
                "priority": "TEXT NOT NULL DEFAULT 'normal'",
            }
            for column, definition in migrations.items():
                if column not in existing_columns:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
            connection.execute(
                "UPDATE jobs SET status='queued', execution_state='queued', waiting_for_json=NULL "
                "WHERE status='processing'"
            )
            connection.execute(
                """UPDATE stage_tasks SET state='queued', waiting_for_json=NULL, resource_id=NULL,
                    updated_at=? WHERE state IN ('running','waiting_resource','cancelling')""",
                (utc_now(),),
            )
            connection.execute(
                "UPDATE workflows SET status='waiting', updated_at=? WHERE status='running'",
                (utc_now(),),
            )
            connection.execute(
                """UPDATE stage_attempts SET state='interrupted', finished_at=?, error='Application restarted'
                WHERE state='running'""",
                (utc_now(),),
            )
            connection.execute(
                "UPDATE resource_leases SET released_at=? WHERE released_at IS NULL",
                (utc_now(),),
            )
            self._migrate_legacy_jobs(connection)
            self._reconcile_terminal_workflows(connection)
            connection.execute("PRAGMA optimize")

    @staticmethod
    def _reconcile_terminal_workflows(connection: sqlite3.Connection) -> None:
        """Close active stage rows that survived after their workflow became terminal."""
        now = utc_now()
        rows = connection.execute(
            """SELECT stage_tasks.*, workflows.status AS workflow_status
            FROM stage_tasks JOIN workflows ON workflows.id=stage_tasks.workflow_id
            WHERE workflows.status IN ('ready','requires_attention','stopped')
              AND stage_tasks.state IN (
                'blocked','queued','waiting_resource','running','retry_scheduled','cancelling'
              )"""
        ).fetchall()
        for row in rows:
            state = "cancelled" if row["workflow_status"] == "stopped" else "skipped"
            message = (
                "Recovered terminal workflow: pending stage cancelled"
                if state == "cancelled"
                else "Recovered terminal workflow: pending stage skipped"
            )
            connection.execute(
                """UPDATE stage_tasks SET state=?, waiting_for_json=NULL, resource_id=NULL,
                    updated_at=?, finished_at=? WHERE id=?""",
                (state, now, now, row["id"]),
            )
            connection.execute(
                """INSERT INTO pipeline_events(
                    workflow_id, stage_task_id, video_id, stage, event, from_state,
                    to_state, message, created_at
                ) VALUES (?, ?, ?, ?, 'reconciled', ?, ?, ?, ?)""",
                (
                    row["workflow_id"],
                    row["id"],
                    row["video_id"],
                    row["stage"],
                    row["state"],
                    state,
                    message,
                    now,
                ),
            )

    def _migrate_legacy_jobs(self, connection: sqlite3.Connection) -> None:
        """Create durable workflow records for jobs from the compatibility schema."""
        rows = connection.execute("SELECT * FROM jobs WHERE workflow_id='' OR workflow_id IS NULL").fetchall()
        for row in rows:
            workflow_id = str(uuid.uuid4())
            now = row["updated_at"] or utc_now()
            status = "waiting" if row["status"] == "queued" else self._workflow_status(row["status"])
            connection.execute(
                """INSERT OR IGNORE INTO workflows(
                    id, video_id, kind, status, priority, settings_snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'normal', '{}', ?, ?)""",
                (workflow_id, row["video_id"], row["kind"], status, row["created_at"], now),
            )
            state = self._execution_state(row["status"])
            connection.execute(
                "UPDATE jobs SET workflow_id=?, execution_state=? WHERE id=?",
                (workflow_id, state, row["id"]),
            )
            task_id = str(uuid.uuid4())
            connection.execute(
                """INSERT OR IGNORE INTO stage_tasks(
                    id, workflow_id, video_id, stage, state, required, progress,
                    created_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                (
                    task_id,
                    workflow_id,
                    row["video_id"],
                    row["stage"] or "queued",
                    state,
                    row["progress"],
                    row["created_at"],
                    now,
                    now if state in {"succeeded", "failed", "cancelled"} else None,
                ),
            )

    @staticmethod
    def _execution_state(status: str) -> str:
        return {
            "queued": "queued",
            "processing": "running",
            "complete": "succeeded",
            "attention": "failed",
            "cancelled": "cancelled",
        }.get(status, "queued")

    @staticmethod
    def _workflow_status(status: str) -> str:
        return {
            "queued": "waiting",
            "processing": "running",
            "complete": "ready",
            "attention": "requires_attention",
            "cancelled": "stopped",
        }.get(status, "waiting")

    def create_placeholder(self, video_id: str, source_url: str, playlists: list[PlaylistRef] | None = None) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO videos(video_id, source_url, title, status, playlists_json, added_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?, ?)
                ON CONFLICT(video_id) DO NOTHING
                """,
                (video_id, source_url, "Ожидает метаданные", json.dumps([item.model_dump(mode="json") for item in playlists or []], ensure_ascii=False), now, now),
            )

    def import_playlist(self, playlist: PlaylistMeta, entries: list[tuple[str, str, int]]) -> tuple[list[JobRecord], list[str]]:
        """Import every distinct playlist entry while retaining playlist membership."""
        jobs: list[JobRecord] = []
        existing: list[str] = []
        now = utc_now()
        with self._connect() as connection:
            next_position = connection.execute("SELECT COALESCE(MAX(position), 0) FROM jobs WHERE status='queued'").fetchone()[0]
            for video_id, source_url, position in entries:
                ref = PlaylistRef(id=playlist.id, title=playlist.title, source_url=playlist.source_url, position=position)
                row = connection.execute("SELECT playlists_json FROM videos WHERE video_id=?", (video_id,)).fetchone()
                if row:
                    refs = [PlaylistRef.model_validate(value) for value in json.loads(row["playlists_json"] or "[]")]
                    refs = [item for item in refs if item.id != playlist.id] + [ref]
                    connection.execute("UPDATE videos SET playlists_json=?, updated_at=? WHERE video_id=?", (json.dumps([item.model_dump(mode="json") for item in refs], ensure_ascii=False), now, video_id))
                    existing.append(video_id)
                    continue
                connection.execute("INSERT INTO videos(video_id, source_url, title, status, playlists_json, added_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?, ?)", (video_id, source_url, "Ожидает метаданные", json.dumps([ref.model_dump(mode="json")], ensure_ascii=False), now, now))
                next_position += 1
                workflow_id = str(uuid.uuid4())
                job = JobRecord(
                    id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    video_id=video_id,
                    source_url=source_url,
                    position=next_position,
                )
                self._insert_workflow(connection, job, {})
                self._insert_job(connection, job)
                self._insert_initial_stage(connection, job)
                jobs.append(job)
        return jobs, existing

    def list_playlists(self) -> list[dict[str, Any]]:
        playlists: dict[str, dict[str, Any]] = {}
        with self._connect() as connection:
            rows = connection.execute("SELECT video_id, playlists_json FROM videos").fetchall()
        for row in rows:
            for payload in json.loads(row["playlists_json"] or "[]"):
                ref = PlaylistRef.model_validate(payload)
                item = playlists.setdefault(ref.id, {**ref.model_dump(mode="json"), "video_count": 0, "video_ids": []})
                item["video_count"] += 1
                item["video_ids"].append(row["video_id"])
        return sorted(playlists.values(), key=lambda item: item["title"].casefold())

    def video_exists(self, video_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1 FROM videos WHERE video_id=?", (video_id,)).fetchone() is not None

    def create_video_folder(self, meta: VideoMeta) -> Path:
        existing = self.find_video_folder(meta.video_id)
        desired = self.library_dir / safe_folder_name(meta.title, meta.published_at, meta.video_id)
        if existing and existing != desired and existing.exists() and not desired.exists():
            existing.rename(desired)
        desired.mkdir(parents=True, exist_ok=True)
        return desired

    def find_video_folder(self, video_id: str) -> Path | None:
        with self._connect() as connection:
            row = connection.execute("SELECT folder FROM videos WHERE video_id=?", (video_id,)).fetchone()
        if row and row["folder"]:
            path = Path(row["folder"])
            if path.exists():
                return path
        for meta_path in self.library_dir.glob("*/.meta.json"):
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("video_id") == video_id:
                return meta_path.parent
        return None

    def save_meta(self, meta: VideoMeta, folder: Path) -> None:
        # Archiving is a library-level user action.  Background jobs often hold
        # an older ``VideoMeta`` instance while they download or summarize, so
        # never let such an instance undo a later archive/restore operation.
        with self._connect() as connection:
            row = connection.execute("SELECT archived FROM videos WHERE video_id=?", (meta.video_id,)).fetchone()
        if row is not None:
            meta.archived = bool(row["archived"])
        meta.updated_at = utc_now()
        meta_path = folder / ".meta.json"
        temporary = meta_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(meta.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(meta_path)
        self.upsert_video(meta, folder)

    def upsert_video(self, meta: VideoMeta, folder: Path | None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO videos(
                    video_id, source_url, title, channel, published_at, duration_seconds,
                    thumbnail_file, thumbnail_url, folder, status, favorite, archived, tags_json,
                    transcript_language, transcript_kind, playlists_json, added_at, updated_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    source_url=excluded.source_url, title=excluded.title, channel=excluded.channel,
                    published_at=excluded.published_at, duration_seconds=excluded.duration_seconds,
                    thumbnail_file=excluded.thumbnail_file, thumbnail_url=excluded.thumbnail_url,
                    folder=excluded.folder, status=excluded.status, favorite=excluded.favorite, archived=excluded.archived,
                    tags_json=excluded.tags_json, transcript_language=excluded.transcript_language,
                    transcript_kind=excluded.transcript_kind, playlists_json=excluded.playlists_json, updated_at=excluded.updated_at, error=excluded.error
                """,
                (
                    meta.video_id, meta.source_url, meta.title, meta.channel, meta.published_at,
                    meta.duration_seconds, meta.thumbnail_file, meta.thumbnail_url,
                    str(folder) if folder else None, meta.status, int(meta.favorite), int(meta.archived),
                    json.dumps(meta.tags, ensure_ascii=False),
                    meta.transcript.language if meta.transcript else None,
                    meta.transcript.kind if meta.transcript else None,
                    json.dumps([item.model_dump(mode="json") for item in meta.playlists], ensure_ascii=False),
                    meta.added_at, meta.updated_at, meta.error,
                ),
            )
        self.update_search(meta.video_id)

    def read_meta(self, video_id: str) -> tuple[VideoMeta, Path] | None:
        folder = self.find_video_folder(video_id)
        if not folder:
            return None
        path = folder / ".meta.json"
        if not path.exists():
            return None
        return VideoMeta.model_validate_json(path.read_text(encoding="utf-8")), folder

    def get_video(self, video_id: str) -> VideoDetail | None:
        stored = self.read_meta(video_id)
        if stored:
            meta, folder = stored
            transcript_files = [item.file for item in meta.transcripts if item.file]
            if not transcript_files and (folder / "transcript.md").exists():
                transcript_files = ["transcript.md"]
            transcript_markdowns = {
                filename: (folder / filename).read_text(encoding="utf-8")
                for filename in transcript_files
                if (folder / filename).is_file()
            }
            transcript = transcript_markdowns.get(meta.transcript.file if meta.transcript else "", "")
            if not transcript:
                transcript = next(iter(transcript_markdowns.values()), "")
            summary = (folder / "summary.md").read_text(encoding="utf-8") if (folder / "summary.md").exists() else ""
            artifacts = [item for item in meta.prompt_artifacts if (folder / item.file).is_file()]
            return VideoDetail(meta=meta, transcript_markdown=transcript, transcript_markdowns=transcript_markdowns, summary_markdown=summary, prompt_artifacts=artifacts, folder=str(folder))
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
        if not row:
            return None
        meta = self._row_to_meta(row)
        return VideoDetail(meta=meta)

    def list_videos(self, query: str = "", status: str = "", favorite: bool | None = None, archived: bool = False, sort: str = "added_desc") -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        clauses.append("archived = ?")
        values.append(int(archived))
        if status:
            clauses.append("status = ?")
            values.append(status)
        if favorite is not None:
            clauses.append("favorite = ?")
            values.append(int(favorite))
        if query:
            clauses.append("video_id IN (SELECT video_id FROM video_search WHERE video_search MATCH ?)")
            values.append('"' + query.replace('"', '""') + '"*')
        order_by = {
            "added_asc": "added_at ASC",
            "title": "title COLLATE NOCASE ASC",
            "published": "published_at DESC, added_at DESC",
        }.get(sort, "added_at DESC")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM videos {where} ORDER BY {order_by}", values).fetchall()
        return [self._row_to_meta(row).model_dump(mode="json") | {"folder": row["folder"]} for row in rows]

    def patch_video(self, video_id: str, favorite: bool | None, tags: list[str] | None, archived: bool | None = None) -> VideoMeta | None:
        if archived is not None:
            with self._connect() as connection:
                exists = connection.execute(
                    "UPDATE videos SET archived=?, updated_at=? WHERE video_id=?",
                    (int(archived), utc_now(), video_id),
                ).rowcount > 0
            if not exists:
                return None
        stored = self.read_meta(video_id)
        if not stored:
            detail = self.get_video(video_id) if archived is not None else None
            return detail.meta if detail else None
        meta, folder = stored
        if favorite is not None:
            meta.favorite = favorite
        if tags is not None:
            meta.tags = sorted({tag.strip() for tag in tags if tag.strip()}, key=str.casefold)
        if archived is not None:
            meta.archived = archived
        self.save_meta(meta, folder)
        return meta

    def update_search(self, video_id: str) -> None:
        detail = self.get_video_without_search(video_id)
        if not detail:
            return
        with self._connect() as connection:
            connection.execute("DELETE FROM video_search WHERE video_id=?", (video_id,))
            connection.execute(
                "INSERT INTO video_search(video_id, title, channel, tags, transcript, summary) VALUES (?, ?, ?, ?, ?, ?)",
                (video_id, detail.meta.title, detail.meta.channel, " ".join(detail.meta.tags), detail.transcript_markdown, detail.summary_markdown),
            )

    def get_video_without_search(self, video_id: str) -> VideoDetail | None:
        stored = self.read_meta(video_id)
        if not stored:
            return None
        meta, folder = stored
        transcript_files = [item.file for item in meta.transcripts if item.file]
        if not transcript_files and (folder / "transcript.md").exists():
            transcript_files = ["transcript.md"]
        transcript_markdowns = {filename: (folder / filename).read_text(encoding="utf-8") for filename in transcript_files if (folder / filename).is_file()}
        summary_path = folder / "summary.md"
        transcript = transcript_markdowns.get(meta.transcript.file if meta.transcript else "", next(iter(transcript_markdowns.values()), ""))
        artifacts = [item for item in meta.prompt_artifacts if (folder / item.file).is_file()]
        return VideoDetail(meta=meta, transcript_markdown=transcript, transcript_markdowns=transcript_markdowns, summary_markdown=summary_path.read_text(encoding="utf-8") if summary_path.exists() else "", prompt_artifacts=artifacts, folder=str(folder))

    def read_prompt_artifact(self, video_id: str, artifact_id: str) -> tuple[PromptArtifact, str] | None:
        stored = self.read_meta(video_id)
        if not stored:
            return None
        meta, folder = stored
        artifact = next((item for item in meta.prompt_artifacts if item.id == artifact_id), None)
        if not artifact:
            return None
        path = folder / artifact.file
        if not path.is_file() or path.parent.resolve().parent != folder.resolve():
            return None
        return artifact, path.read_text(encoding="utf-8")

    def rescan(self) -> int:
        count = 0
        for meta_path in self.library_dir.glob("*/.meta.json"):
            try:
                meta = VideoMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            self.upsert_video(meta, meta_path.parent)
            count += 1
        return count

    def mark_summaries_stale(self) -> int:
        count = 0
        for meta_path in self.library_dir.glob("*/.meta.json"):
            try:
                meta = VideoMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not meta.current_summary:
                continue
            meta.summary_stale = True
            meta.status = "stale"
            self.save_meta(meta, meta_path.parent)
            count += 1
        return count

    def delete_video(self, video_id: str, delete_files: bool) -> bool:
        folder = self.find_video_folder(video_id)
        with self._connect() as connection:
            existed = connection.execute("DELETE FROM videos WHERE video_id=?", (video_id,)).rowcount > 0
            connection.execute("DELETE FROM video_search WHERE video_id=?", (video_id,))
        if delete_files and folder and folder.exists() and folder.parent == self.library_dir:
            shutil.rmtree(folder)
        return existed

    def enqueue(
        self,
        video_id: str,
        source_url: str,
        kind: str = "process",
        overrides: dict[str, Any] | None = None,
        *,
        workflow_id: str | None = None,
        settings_snapshot: dict[str, Any] | None = None,
        priority: str = "normal",
    ) -> JobRecord:
        with self._connect() as connection:
            next_position = connection.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM jobs WHERE status='queued'").fetchone()[0]
            job = JobRecord(
                id=str(uuid.uuid4()),
                workflow_id=workflow_id or str(uuid.uuid4()),
                video_id=video_id,
                source_url=source_url,
                kind=kind,
                position=next_position,
                overrides=overrides or {},
                priority=priority,  # type: ignore[arg-type]
            )
            if not workflow_id:
                self._insert_workflow(connection, job, settings_snapshot or {})
            self._insert_job(connection, job)
            self._insert_initial_stage(connection, job)
        return job

    @staticmethod
    def _insert_workflow(connection: sqlite3.Connection, job: JobRecord, settings_snapshot: dict[str, Any]) -> None:
        connection.execute(
            """INSERT INTO workflows(
                id, video_id, kind, status, priority, settings_snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, 'waiting', ?, ?, ?, ?)""",
            (
                job.workflow_id,
                job.video_id,
                job.kind,
                job.priority,
                json.dumps(settings_snapshot, ensure_ascii=False),
                job.created_at,
                job.updated_at,
            ),
        )

    @staticmethod
    def _insert_job(connection: sqlite3.Connection, job: JobRecord) -> None:
        connection.execute(
            """INSERT INTO jobs (
                id, video_id, source_url, kind, status, stage, progress, position,
                attempts, created_at, updated_at, error, log_json, stage_log_json,
                requests_planned, requests_completed, summary_source, provider_id,
                provider_name, model, overrides_json, workflow_id, execution_state,
                waiting_for_json, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id,
                job.video_id,
                job.source_url,
                job.kind,
                job.status,
                job.stage,
                job.progress,
                job.position,
                job.attempts,
                job.created_at,
                job.updated_at,
                job.error,
                json.dumps(job.log),
                json.dumps([]),
                job.requests_planned,
                job.requests_completed,
                job.summary_source,
                job.provider_id,
                job.provider_name,
                job.model,
                json.dumps(job.overrides),
                job.workflow_id,
                job.execution_state,
                json.dumps(job.waiting_for) if job.waiting_for else None,
                job.priority,
            ),
        )

    @staticmethod
    def _insert_initial_stage(connection: sqlite3.Connection, job: JobRecord) -> None:
        task_id = str(uuid.uuid4())
        connection.execute(
            """INSERT OR IGNORE INTO stage_tasks(
                id, workflow_id, video_id, stage, state, required, progress, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', 'queued', 1, 0, ?, ?)""",
            (task_id, job.workflow_id, job.video_id, job.created_at, job.updated_at),
        )
        connection.execute(
            """INSERT INTO pipeline_events(
                workflow_id, stage_task_id, video_id, stage, event, to_state, message, created_at
            ) VALUES (?, ?, ?, 'queued', 'created', 'queued', 'Workflow queued', ?)""",
            (job.workflow_id, task_id, job.video_id, job.created_at),
        )

    def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY CASE WHEN status='processing' THEN 0 WHEN status='queued' THEN 1 ELSE 2 END, position, updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(row) for row in rows]

    def next_job(self, kinds: tuple[str, ...] | None = None) -> JobRecord | None:
        with self._connect() as connection:
            if kinds:
                placeholders = ",".join("?" for _ in kinds)
                row = connection.execute(
                    f"SELECT * FROM jobs WHERE status='queued' AND kind IN ({placeholders}) ORDER BY position LIMIT 1",
                    kinds,
                ).fetchone()
            else:
                row = connection.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY position LIMIT 1").fetchone()
            if not row:
                return None
            connection.execute(
                "UPDATE jobs SET status='processing', stage='starting', execution_state='running', updated_at=? WHERE id=?",
                (utc_now(), row["id"]),
            )
            connection.execute(
                "UPDATE workflows SET status='running', updated_at=? WHERE id=?",
                (utc_now(), row["workflow_id"]),
            )
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        return self._row_to_job(row)

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def delete_finished_job(self, job_id: str) -> bool | None:
        """Delete one terminal history record, never a video's artifacts.

        ``None`` distinguishes an active job from a job that no longer exists,
        so the API can return a useful conflict response instead of racing the
        worker and removing a record it is still updating.
        """
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return False
            if row["status"] not in {"complete", "attention"}:
                return None
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))

        # Job logs are internal diagnostic data, not video artifacts.  Keep
        # failure-to-clean-up non-fatal: the history record is already gone.
        (self.logs_dir / f"{job_id}.log").unlink(missing_ok=True)
        return True

    def update_job(self, job_id: str, **changes: Any) -> JobRecord | None:
        allowed = {"status", "stage", "progress", "position", "attempts", "error", "log_json", "stage_log_json", "requests_planned", "requests_completed", "summary_source", "provider_id", "provider_name", "model", "overrides_json", "execution_state", "waiting_for_json", "priority"}
        columns = []
        values = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            columns.append(f"{key}=?")
            values.append(json.dumps(value, ensure_ascii=False) if key.endswith("_json") else value)
        if not columns:
            return self.get_job(job_id)
        columns.append("updated_at=?")
        values.extend([utc_now(), job_id])
        with self._connect() as connection:
            connection.execute(f"UPDATE jobs SET {', '.join(columns)} WHERE id=?", values)
        return self.get_job(job_id)

    def transition_stage(
        self,
        job_id: str,
        stage: str,
        state: str,
        *,
        progress: float | None = None,
        waiting_for: dict[str, Any] | None = None,
        resource_id: str | None = None,
        message: str = "",
        error: str | None = None,
        required: bool = True,
    ) -> StageTaskRecord:
        """Persist one truthful stage transition and its monotonic event."""
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")
        now = utc_now()
        with self._connect() as connection:
            if stage != "queued":
                connection.execute(
                    """UPDATE stage_tasks SET state='succeeded', progress=1, updated_at=?, finished_at=?
                    WHERE workflow_id=? AND stage='queued' AND state='queued'""",
                    (now, now, job.workflow_id),
                )
            row = connection.execute(
                "SELECT * FROM stage_tasks WHERE workflow_id=? AND stage=?",
                (job.workflow_id, stage),
            ).fetchone()
            previous_state = row["state"] if row else None
            task_id = row["id"] if row else str(uuid.uuid4())
            next_progress = progress if progress is not None else (row["progress"] if row else 0)
            started_at = row["started_at"] if row else None
            if state == "running" and not started_at:
                started_at = now
            finished_at = now if state in {"succeeded", "failed", "cancelled", "skipped"} else None
            waiting_json = json.dumps(waiting_for, ensure_ascii=False) if waiting_for else None
            if row:
                connection.execute(
                    """UPDATE stage_tasks SET state=?, required=?, progress=?, waiting_for_json=?,
                        resource_id=?, error=?, updated_at=?, started_at=?, finished_at=? WHERE id=?""",
                    (
                        state,
                        int(required),
                        next_progress,
                        waiting_json,
                        resource_id,
                        error,
                        now,
                        started_at,
                        finished_at,
                        task_id,
                    ),
                )
            else:
                connection.execute(
                    """INSERT INTO stage_tasks(
                        id, workflow_id, video_id, stage, state, required, progress,
                        waiting_for_json, resource_id, error, created_at, updated_at,
                        started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        task_id,
                        job.workflow_id,
                        job.video_id,
                        stage,
                        state,
                        int(required),
                        next_progress,
                        waiting_json,
                        resource_id,
                        error,
                        now,
                        now,
                        started_at,
                        finished_at,
                    ),
                )
            connection.execute(
                """INSERT INTO pipeline_events(
                    workflow_id, stage_task_id, video_id, stage, event, from_state,
                    to_state, message, resource_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, 'transition', ?, ?, ?, ?, ?, ?)""",
                (
                    job.workflow_id,
                    task_id,
                    job.video_id,
                    stage,
                    previous_state,
                    state,
                    message,
                    resource_id,
                    json.dumps({"progress": next_progress, "waiting_for": waiting_for}, ensure_ascii=False),
                    now,
                ),
            )
            legacy_status = {
                "queued": "queued",
                "blocked": "queued",
                "waiting_resource": "processing",
                "running": "processing",
                "retry_scheduled": "queued",
                "cancelling": "processing",
                "succeeded": job.status,
                "failed": "attention",
                "cancelled": "cancelled",
                "skipped": job.status,
            }[state]
            connection.execute(
                """UPDATE jobs SET stage=?, execution_state=?, waiting_for_json=?,
                    progress=?, error=?, status=?, updated_at=? WHERE id=?""",
                (stage, state, waiting_json, next_progress, error, legacy_status, now, job_id),
            )
            if state in {"running", "waiting_resource"}:
                connection.execute(
                    "UPDATE workflows SET status='running', updated_at=? WHERE id=?",
                    (now, job.workflow_id),
                )
            elif state == "failed" and required:
                connection.execute(
                    "UPDATE workflows SET status='requires_attention', updated_at=? WHERE id=?",
                    (now, job.workflow_id),
                )
        restored = self.get_stage_task(job.workflow_id, stage)
        if not restored:
            raise RuntimeError("Stage transition was not persisted")
        return restored

    def finish_workflow(self, job_id: str, outcome: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        now = utc_now()
        workflow_status = {
            "complete": "ready",
            "attention": "requires_attention",
            "cancelled": "stopped",
        }.get(outcome, outcome)
        with self._connect() as connection:
            connection.execute(
                "UPDATE workflows SET status=?, updated_at=?, completed_at=? WHERE id=?",
                (workflow_status, now, now, job.workflow_id),
            )
            rows = connection.execute(
                """SELECT * FROM stage_tasks WHERE workflow_id=? AND state IN (
                    'blocked','queued','waiting_resource','running','retry_scheduled','cancelling'
                )""",
                (job.workflow_id,),
            ).fetchall()
            terminal_state = "cancelled" if workflow_status == "stopped" else "skipped"
            for row in rows:
                connection.execute(
                    """UPDATE stage_tasks SET state=?, waiting_for_json=NULL, resource_id=NULL,
                        updated_at=?, finished_at=? WHERE id=?""",
                    (terminal_state, now, now, row["id"]),
                )
                connection.execute(
                    """INSERT INTO pipeline_events(
                        workflow_id, stage_task_id, video_id, stage, event, from_state,
                        to_state, message, created_at
                    ) VALUES (?, ?, ?, ?, 'workflow-finished', ?, ?, ?, ?)""",
                    (
                        job.workflow_id,
                        row["id"],
                        job.video_id,
                        row["stage"],
                        row["state"],
                        terminal_state,
                        f"Workflow finished with status {workflow_status}",
                        now,
                    ),
                )

    def start_attempt(self, job_id: str, stage: str, resource_id: str, worker_id: str = "local") -> str:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")
        task = self.get_stage_task(job.workflow_id, stage)
        if not task:
            raise KeyError(f"Stage {stage} not found")
        attempt_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as connection:
            ordinal = int(connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM stage_attempts WHERE stage_task_id=?",
                (task.id,),
            ).fetchone()[0])
            connection.execute(
                """INSERT INTO stage_attempts(
                    id, stage_task_id, workflow_id, video_id, ordinal, state,
                    resource_id, worker_id, started_at, heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)""",
                (attempt_id, task.id, job.workflow_id, job.video_id, ordinal, resource_id, worker_id, now, now),
            )
            connection.execute("UPDATE stage_tasks SET attempt=? WHERE id=?", (ordinal, task.id))
        return attempt_id

    def acquire_resource_lease(self, attempt_id: str, resource_id: str, workflow_id: str, video_id: str, expires_at: str) -> str:
        lease_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO resource_leases(
                    id, resource_id, attempt_id, workflow_id, video_id, acquired_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (lease_id, resource_id, attempt_id, workflow_id, video_id, utc_now(), expires_at),
            )
        return lease_id

    def heartbeat_attempt(self, attempt_id: str, lease_id: str, expires_at: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("UPDATE stage_attempts SET heartbeat_at=? WHERE id=? AND state='running'", (now, attempt_id))
            connection.execute("UPDATE resource_leases SET expires_at=? WHERE id=? AND released_at IS NULL", (expires_at, lease_id))

    def finish_attempt(self, attempt_id: str, lease_id: str, state: str, error: str | None = None) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE stage_attempts SET state=?, finished_at=?, heartbeat_at=?, error=? WHERE id=?",
                (state, now, now, error, attempt_id),
            )
            connection.execute("UPDATE resource_leases SET released_at=? WHERE id=?", (now, lease_id))

    def list_attempts(self, workflow_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM stage_attempts WHERE workflow_id=? ORDER BY started_at, ordinal",
                (workflow_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_stage_task(self, workflow_id: str, stage: str) -> StageTaskRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM stage_tasks WHERE workflow_id=? AND stage=?",
                (workflow_id, stage),
            ).fetchone()
        return self._row_to_stage_task(row) if row else None

    def list_stage_tasks(self, *, workflow_id: str | None = None, live_only: bool = False) -> list[StageTaskRecord]:
        clauses: list[str] = []
        values: list[Any] = []
        if workflow_id:
            clauses.append("workflow_id=?")
            values.append(workflow_id)
        if live_only:
            clauses.append("state IN ('blocked','queued','waiting_resource','running','retry_scheduled','cancelling','failed')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM stage_tasks {where} ORDER BY updated_at DESC",
                values,
            ).fetchall()
        return [self._row_to_stage_task(row) for row in rows]

    def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        return self._row_to_workflow(row) if row else None

    def list_workflows(self, *, video_id: str | None = None, limit: int = 100) -> list[WorkflowRecord]:
        if video_id:
            sql = "SELECT * FROM workflows WHERE video_id=? ORDER BY updated_at DESC LIMIT ?"
            values: tuple[Any, ...] = (video_id, limit)
        else:
            sql = "SELECT * FROM workflows ORDER BY updated_at DESC LIMIT ?"
            values = (limit,)
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [self._row_to_workflow(row) for row in rows]

    def list_pipeline_events(self, *, after: int = 0, workflow_id: str | None = None, limit: int = 500) -> list[PipelineEventRecord]:
        clauses = ["sequence>?"]
        values: list[Any] = [after]
        if workflow_id:
            clauses.append("workflow_id=?")
            values.append(workflow_id)
        values.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM pipeline_events WHERE {' AND '.join(clauses)} ORDER BY sequence LIMIT ?",
                values,
            ).fetchall()
        return [self._row_to_pipeline_event(row) for row in rows]

    def pipeline_cursor(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM pipeline_events").fetchone()[0])

    def pipeline_aggregates(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT stage, state, COUNT(*) AS count
                FROM stage_tasks GROUP BY stage, state ORDER BY stage, state"""
            ).fetchall()
            videos = connection.execute(
                """SELECT stage, video_id, state, updated_at FROM stage_tasks
                WHERE state IN ('blocked','queued','waiting_resource','running','retry_scheduled','cancelling','failed')
                ORDER BY updated_at DESC"""
            ).fetchall()
        by_stage: dict[str, dict[str, Any]] = {}
        for row in rows:
            stage = row["stage"].split(":", 1)[0]
            item = by_stage.setdefault(stage, {"id": stage, "states": {}, "video_ids": []})
            item["states"][row["state"]] = item["states"].get(row["state"], 0) + row["count"]
        for row in videos:
            stage = row["stage"].split(":", 1)[0]
            item = by_stage.setdefault(stage, {"id": stage, "states": {}, "video_ids": []})
            if row["video_id"] not in item["video_ids"] and len(item["video_ids"]) < 12:
                item["video_ids"].append(row["video_id"])
        for item in by_stage.values():
            states = item["states"]
            item["count"] = sum(states.get(state, 0) for state in ("blocked", "queued", "waiting_resource", "running", "retry_scheduled", "cancelling"))
            item["running"] = states.get("running", 0)
            item["waiting"] = states.get("waiting_resource", 0) + states.get("retry_scheduled", 0)
            item["queued"] = states.get("queued", 0)
            item["blocked"] = states.get("blocked", 0)
            item["failed"] = states.get("failed", 0)
            item["succeeded"] = states.get("succeeded", 0)
            item["cancelled"] = states.get("cancelled", 0)
            item["skipped"] = states.get("skipped", 0)
        return list(by_stage.values())

    @staticmethod
    def _row_to_stage_task(row: sqlite3.Row) -> StageTaskRecord:
        return StageTaskRecord(
            id=row["id"],
            workflow_id=row["workflow_id"],
            video_id=row["video_id"],
            stage=row["stage"],
            state=row["state"],
            required=bool(row["required"]),
            progress=row["progress"],
            waiting_for=json.loads(row["waiting_for_json"]) if row["waiting_for_json"] else None,
            resource_id=row["resource_id"],
            attempt=row["attempt"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def _row_to_pipeline_event(row: sqlite3.Row) -> PipelineEventRecord:
        return PipelineEventRecord(
            sequence=row["sequence"],
            workflow_id=row["workflow_id"],
            stage_task_id=row["stage_task_id"],
            video_id=row["video_id"],
            stage=row["stage"],
            event=row["event"],
            from_state=row["from_state"],
            to_state=row["to_state"],
            message=row["message"],
            resource_id=row["resource_id"],
            payload=json.loads(row["payload_json"] or "{}"),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_workflow(row: sqlite3.Row) -> WorkflowRecord:
        return WorkflowRecord(
            id=row["id"],
            video_id=row["video_id"],
            kind=row["kind"],
            status=row["status"],
            priority=row["priority"],
            settings_snapshot=json.loads(row["settings_snapshot_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            paused_at=row["paused_at"],
            completed_at=row["completed_at"],
        )

    def reorder_jobs(self, job_ids: list[str]) -> None:
        with self._connect() as connection:
            for position, job_id in enumerate(job_ids, start=1):
                connection.execute("UPDATE jobs SET position=?, updated_at=? WHERE id=? AND status='queued'", (position, utc_now(), job_id))

    def write_job_log(self, job: JobRecord) -> None:
        path = self.logs_dir / f"{job.id}.log"
        path.write_text("\n".join(job.log).rstrip() + "\n", encoding="utf-8")

    def cleanup_logs(self, retention_days: int) -> int:
        cutoff = time.time() - retention_days * 86400
        removed = 0
        for path in self.logs_dir.glob("*.log"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        keys = set(row.keys())
        return JobRecord(id=row["id"], video_id=row["video_id"], source_url=row["source_url"], kind=row["kind"], status=row["status"], stage=row["stage"], progress=row["progress"], position=row["position"], attempts=row["attempts"], created_at=row["created_at"], updated_at=row["updated_at"], error=row["error"], log=json.loads(row["log_json"]), stage_log=json.loads(row["stage_log_json"]), requests_planned=row["requests_planned"], requests_completed=row["requests_completed"], summary_source=row["summary_source"], provider_id=row["provider_id"], provider_name=row["provider_name"], model=row["model"], overrides=json.loads(row["overrides_json"]), workflow_id=row["workflow_id"] if "workflow_id" in keys else "", execution_state=row["execution_state"] if "execution_state" in keys else LibraryStorage._execution_state(row["status"]), waiting_for=json.loads(row["waiting_for_json"]) if "waiting_for_json" in keys and row["waiting_for_json"] else None, priority=row["priority"] if "priority" in keys else "normal")

    @staticmethod
    def _row_to_meta(row: sqlite3.Row) -> VideoMeta:
        return VideoMeta(video_id=row["video_id"], source_url=row["source_url"], title=row["title"], channel=row["channel"], published_at=row["published_at"], duration_seconds=row["duration_seconds"], thumbnail_file=row["thumbnail_file"], thumbnail_url=row["thumbnail_url"], added_at=row["added_at"], updated_at=row["updated_at"], status=row["status"], favorite=bool(row["favorite"]), archived=bool(row["archived"]), tags=json.loads(row["tags_json"]), playlists=[PlaylistRef.model_validate(value) for value in json.loads(row["playlists_json"] or "[]")], error=row["error"])
