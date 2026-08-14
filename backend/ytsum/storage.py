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

from .models import JobRecord, VideoDetail, VideoMeta, utc_now


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
                overrides_json TEXT NOT NULL DEFAULT '{}'
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_position ON jobs(status, position)",
            "CREATE VIRTUAL TABLE IF NOT EXISTS video_search USING fts5(video_id UNINDEXED, title, channel, tags, transcript, summary)",
        ]
        with self._connect() as connection:
            for statement in statements:
                connection.execute(statement)
            connection.execute("UPDATE jobs SET status='queued', stage='queued' WHERE status='processing'")
            connection.execute("PRAGMA optimize")

    def create_placeholder(self, video_id: str, source_url: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO videos(video_id, source_url, title, status, added_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?)
                ON CONFLICT(video_id) DO NOTHING
                """,
                (video_id, source_url, "Ожидает метаданные", now, now),
            )

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
                    thumbnail_file, thumbnail_url, folder, status, favorite, tags_json,
                    transcript_language, transcript_kind, added_at, updated_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    source_url=excluded.source_url, title=excluded.title, channel=excluded.channel,
                    published_at=excluded.published_at, duration_seconds=excluded.duration_seconds,
                    thumbnail_file=excluded.thumbnail_file, thumbnail_url=excluded.thumbnail_url,
                    folder=excluded.folder, status=excluded.status, favorite=excluded.favorite,
                    tags_json=excluded.tags_json, transcript_language=excluded.transcript_language,
                    transcript_kind=excluded.transcript_kind, updated_at=excluded.updated_at, error=excluded.error
                """,
                (
                    meta.video_id, meta.source_url, meta.title, meta.channel, meta.published_at,
                    meta.duration_seconds, meta.thumbnail_file, meta.thumbnail_url,
                    str(folder) if folder else None, meta.status, int(meta.favorite),
                    json.dumps(meta.tags, ensure_ascii=False),
                    meta.transcript.language if meta.transcript else None,
                    meta.transcript.kind if meta.transcript else None,
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
            transcript = (folder / "transcript.md").read_text(encoding="utf-8") if (folder / "transcript.md").exists() else ""
            summary = (folder / "summary.md").read_text(encoding="utf-8") if (folder / "summary.md").exists() else ""
            return VideoDetail(meta=meta, transcript_markdown=transcript, summary_markdown=summary, folder=str(folder))
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
        if not row:
            return None
        meta = self._row_to_meta(row)
        return VideoDetail(meta=meta)

    def list_videos(self, query: str = "", status: str = "", favorite: bool | None = None, sort: str = "added_desc") -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
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

    def patch_video(self, video_id: str, favorite: bool | None, tags: list[str] | None) -> VideoMeta | None:
        stored = self.read_meta(video_id)
        if not stored:
            return None
        meta, folder = stored
        if favorite is not None:
            meta.favorite = favorite
        if tags is not None:
            meta.tags = sorted({tag.strip() for tag in tags if tag.strip()}, key=str.casefold)
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
        transcript_path = folder / "transcript.md"
        summary_path = folder / "summary.md"
        return VideoDetail(meta=meta, transcript_markdown=transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else "", summary_markdown=summary_path.read_text(encoding="utf-8") if summary_path.exists() else "", folder=str(folder))

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

    def enqueue(self, video_id: str, source_url: str, kind: str = "process", overrides: dict[str, Any] | None = None) -> JobRecord:
        with self._connect() as connection:
            next_position = connection.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM jobs WHERE status='queued'").fetchone()[0]
            job = JobRecord(id=str(uuid.uuid4()), video_id=video_id, source_url=source_url, kind=kind, position=next_position, overrides=overrides or {})
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job.id, job.video_id, job.source_url, job.kind, job.status, job.stage, job.progress, job.position, job.attempts, job.created_at, job.updated_at, job.error, json.dumps(job.log), json.dumps(job.overrides)),
            )
        return job

    def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY CASE WHEN status='processing' THEN 0 WHEN status='queued' THEN 1 ELSE 2 END, position, updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(row) for row in rows]

    def next_job(self) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY position LIMIT 1").fetchone()
            if not row:
                return None
            connection.execute("UPDATE jobs SET status='processing', stage='starting', updated_at=? WHERE id=?", (utc_now(), row["id"]))
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        return self._row_to_job(row)

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def update_job(self, job_id: str, **changes: Any) -> JobRecord | None:
        allowed = {"status", "stage", "progress", "position", "attempts", "error", "log_json", "overrides_json"}
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
        return JobRecord(id=row["id"], video_id=row["video_id"], source_url=row["source_url"], kind=row["kind"], status=row["status"], stage=row["stage"], progress=row["progress"], position=row["position"], attempts=row["attempts"], created_at=row["created_at"], updated_at=row["updated_at"], error=row["error"], log=json.loads(row["log_json"]), overrides=json.loads(row["overrides_json"]))

    @staticmethod
    def _row_to_meta(row: sqlite3.Row) -> VideoMeta:
        return VideoMeta(video_id=row["video_id"], source_url=row["source_url"], title=row["title"], channel=row["channel"], published_at=row["published_at"], duration_seconds=row["duration_seconds"], thumbnail_file=row["thumbnail_file"], thumbnail_url=row["thumbnail_url"], added_at=row["added_at"], updated_at=row["updated_at"], status=row["status"], favorite=bool(row["favorite"]), tags=json.loads(row["tags_json"]), error=row["error"])
