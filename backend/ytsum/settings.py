from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from .models import AppSettings, ProviderSettings, SummaryTemplate


DEFAULT_TEMPLATES = [
    SummaryTemplate(
        id="structured",
        name_ru="Структурированный конспект",
        name_en="Structured notes",
        builtin=True,
        prompt="Create a faithful Markdown summary in {language}. Include a short overview, key ideas, detailed notes, conclusions or actions, and source timestamp links when the input contains them. Do not invent facts or timestamps.",
    ),
    SummaryTemplate(
        id="concise",
        name_ru="Краткое резюме",
        name_en="Concise summary",
        builtin=True,
        prompt="Create a concise Markdown summary in {language}. Preserve the main thesis, the strongest supporting points, and important caveats.",
    ),
    SummaryTemplate(
        id="ideas",
        name_ru="Ключевые идеи",
        name_en="Key ideas",
        builtin=True,
        prompt="Extract the key ideas in {language}. Group related ideas, explain why each matters, and include source timestamp links when available.",
    ),
    SummaryTemplate(
        id="actions",
        name_ru="Практические действия",
        name_en="Practical actions",
        builtin=True,
        prompt="Turn the content into practical actions in {language}. Separate immediate actions, experiments, risks, and open questions. Cite timestamps when available.",
    ),
]

DEFAULT_PROVIDERS = [
    ProviderSettings(
        id="ollama",
        name="Ollama",
        kind="ollama",
        base_url="http://127.0.0.1:11434",
        model="llama3.1",
        requests_per_minute=None,
        remote=False,
        remote_confirmed=True,
    ),
    ProviderSettings(
        id="openai-compatible",
        name="OpenAI-compatible",
        kind="openai",
        base_url="http://127.0.0.1:1234/v1",
        model="",
        requests_per_minute=None,
        remote=False,
        remote_confirmed=True,
    ),
]


def default_settings() -> AppSettings:
    return AppSettings(providers=DEFAULT_PROVIDERS, templates=DEFAULT_TEMPLATES)


class SettingsRepository:
    def __init__(self, state_dir: Path | None = None) -> None:
        configured = os.getenv("YTSUM_STATE_DIR")
        self.state_dir = Path(
            configured or state_dir or "~/Library/Application Support/YTSum"
        ).expanduser()
        self.path = self.state_dir / "settings.json"
        self._lock = RLock()

    def load(self) -> AppSettings:
        with self._lock:
            if not self.path.exists():
                settings = default_settings()
                if library_override := os.getenv("YTSUM_LIBRARY_DIR"):
                    settings.library_dir = library_override
                return settings
            settings = AppSettings.model_validate(
                json.loads(self.path.read_text(encoding="utf-8"))
            )
            self._merge_builtins(settings)
            return settings

    def save(self, settings: AppSettings) -> AppSettings:
        with self._lock:
            self._merge_builtins(settings)
            self.state_dir.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(
                    settings.model_dump(mode="json"), ensure_ascii=False, indent=2
                )
                + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.path)
            return settings

    @staticmethod
    def _merge_builtins(settings: AppSettings) -> None:
        known_templates = {item.id for item in settings.templates}
        settings.templates.extend(
            item for item in DEFAULT_TEMPLATES if item.id not in known_templates
        )
