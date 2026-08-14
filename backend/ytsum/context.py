from __future__ import annotations

from pathlib import Path
from threading import RLock

from .models import AppSettings
from .queue import ProcessingQueue
from .settings import SettingsRepository
from .storage import LibraryStorage


class ApplicationContext:
    def __init__(self) -> None:
        self.settings_repo = SettingsRepository()
        self._lock = RLock()
        settings = self.settings_repo.load()
        self._storage = LibraryStorage(Path(settings.library_dir))
        self.queue = ProcessingQueue(self.settings_repo, self.storage)

    def storage(self) -> LibraryStorage:
        with self._lock:
            return self._storage

    def save_settings(self, settings: AppSettings) -> AppSettings:
        current = self.settings_repo.load()
        old_summary_signature = self._summary_signature(current)
        saved = self.settings_repo.save(settings)
        if Path(current.library_dir).expanduser().resolve() != Path(saved.library_dir).expanduser().resolve():
            with self._lock:
                self._storage = LibraryStorage(Path(saved.library_dir))
                self._storage.rescan()
        if old_summary_signature != self._summary_signature(saved):
            self.storage().mark_summaries_stale()
        return saved

    @staticmethod
    def _summary_signature(settings: AppSettings) -> tuple:
        providers = tuple((item.id, item.base_url, item.model, item.temperature, item.max_output_tokens) for item in settings.providers)
        return (settings.active_provider_id, settings.summary_language, settings.summary_mode, settings.summary_template_id, settings.chunk_characters, providers)
