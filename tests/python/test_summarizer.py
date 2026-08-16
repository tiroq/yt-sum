import asyncio
import tomllib
from pathlib import Path

import pytest

from ytsum.models import AppSettings, ProviderSettings, SummaryTemplate
from ytsum.providers import AsyncRateLimiter, ProviderClient, ProviderError
from ytsum.summarizer import Summarizer, split_text, strip_frontmatter


def test_cluster_dependencies_are_default_dependencies() -> None:
    project_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
    config = tomllib.loads(project_file.read_text())
    dependencies = config["project"]["dependencies"]

    assert any(dep.startswith("sentence-transformers") for dep in dependencies)
    assert any(dep.startswith("scikit-learn") for dep in dependencies)


def test_cluster_mode_reports_clear_missing_dependency_message(monkeypatch) -> None:
    summarizer = Summarizer(AppSettings(), [ProviderSettings(id="x", name="X", kind="openai", base_url="http://example/v1", model="a")], SummaryTemplate(id="t", name_ru="Тест", name_en="Test", prompt="Summarize in {language}."))

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name in {"sentence_transformers", "sklearn", "sklearn.cluster", "numpy"}:
            raise ImportError(f"No module named {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError, match=r"\.venv/bin/pip install -e '\.\[cluster\]'"):
        summarizer._cluster(["paragraph one", "paragraph two"])


def test_split_text_covers_source_and_respects_size() -> None:
    source = "\n\n".join(f"Paragraph {index}: " + "word " * 30 for index in range(20))
    chunks = split_text(source, maximum=420, overlap=0)
    assert len(chunks) > 1
    assert all(len(chunk) <= 420 for chunk in chunks)
    assert "Paragraph 0" in chunks[0]
    assert "Paragraph 19" in chunks[-1]


def test_strip_frontmatter() -> None:
    assert strip_frontmatter("---\nlanguage: en\n---\n\n# Text") == "# Text"


def test_openai_client_accepts_a_full_chat_completions_url() -> None:
    provider = ProviderSettings(
        id="cerebras", name="Cerebras", kind="openai",
        base_url="https://api.cerebras.ai/v1/chat/completions", model="gemma-4-31b",
    )
    assert ProviderClient(provider)._openai_base_url() == "https://api.cerebras.ai/v1"


def test_disabled_provider_does_not_send_chat_request() -> None:
    provider = ProviderSettings(
        id="disabled", name="Disabled", kind="openai",
        base_url="http://disabled/v1", model="a", enabled=False,
    )
    with pytest.raises(ProviderError, match="Disabled is disabled"):
        asyncio.run(ProviderClient(provider).chat(system="system", user="user"))


def test_provider_rejects_request_above_tpm_limit() -> None:
    provider = ProviderSettings(
        id="tpm-small", name="Tiny TPM", kind="openai",
        base_url="http://tpm-small/v1", model="a", tokens_per_minute=10,
    )
    with pytest.raises(ProviderError, match="above the 10 TPM limit"):
        asyncio.run(ProviderClient(provider).chat(system="system", user="user", estimated_tokens=11))


def test_rpm_limiter_spaces_requests_even_when_window_has_capacity(monkeypatch) -> None:
    now = 1000.0
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return now

    async def fake_sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    monkeypatch.setattr("ytsum.providers.time.monotonic", fake_monotonic)
    monkeypatch.setattr("ytsum.providers.asyncio.sleep", fake_sleep)
    limiter = AsyncRateLimiter(5)

    asyncio.run(limiter.acquire())
    asyncio.run(limiter.acquire())

    assert sleeps == [12.0]
    assert limiter.status()["requests_in_window"] == 2
    assert limiter.status()["request_interval_seconds"] == 12.0


def test_request_limiter_respects_hour_and_day_windows(monkeypatch) -> None:
    now = 1000.0
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return now

    async def fake_sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    monkeypatch.setattr("ytsum.providers.time.monotonic", fake_monotonic)
    monkeypatch.setattr("ytsum.providers.asyncio.sleep", fake_sleep)
    limiter = AsyncRateLimiter(None, requests_per_hour=2, requests_per_day=10)

    asyncio.run(limiter.acquire())
    asyncio.run(limiter.acquire())
    asyncio.run(limiter.acquire())

    assert sleeps == [3600.0]
    assert limiter.status()["requests_in_hour"] == 1
    assert limiter.status()["requests_in_day"] == 3


def test_scheduler_retries_a_failed_source_on_another_source(monkeypatch) -> None:
    sources = [
        ProviderSettings(id="offline-retry", name="Offline", kind="openai", base_url="http://offline/v1", model="a"),
        ProviderSettings(id="ready-retry", name="Ready", kind="openai", base_url="http://ready/v1", model="b"),
    ]
    template = SummaryTemplate(id="retry", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")

    async def flaky_chat(self, *, system: str, user: str, model: str | None = None, estimated_tokens: int | None = None) -> str:
        if self.provider.id == "offline-retry":
            raise ProviderError("ConnectTimeout")
        return "summary"

    monkeypatch.setattr(ProviderClient, "chat", flaky_chat)
    result = asyncio.run(Summarizer(AppSettings(), sources, template).run("short transcript", language="en", model="a", mode="complete"))
    assert result.markdown.endswith("summary\n")


def test_map_requests_are_parallel_and_round_robin(monkeypatch) -> None:
    sources = [
        ProviderSettings(id="one", name="One", kind="openai", base_url="http://one/v1", model="a", requests_per_minute=2),
        ProviderSettings(id="two", name="Two", kind="openai", base_url="http://two/v1", model="b", requests_per_minute=3),
    ]
    template = SummaryTemplate(id="test", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")
    summarizer = Summarizer(AppSettings(chunk_characters=1000), sources, template)
    active = 0
    peak = 0
    used: list[str] = []

    async def fake_chat(self, *, system: str, user: str, model: str | None = None, estimated_tokens: int | None = None) -> str:
        nonlocal active, peak
        used.append(self.provider.id)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return f"note from {self.provider.id}"

    monkeypatch.setattr(ProviderClient, "chat", fake_chat)
    source = "\n\n".join(f"Paragraph {index}: " + "word " * 250 for index in range(6))
    result = asyncio.run(summarizer.run(source, language="en", model="a", mode="complete"))
    assert peak > 1
    assert used[:2] == ["one", "two"]
    assert result.provider_ids == ["one", "two"]


def test_scheduler_sends_next_request_to_available_source(monkeypatch) -> None:
    sources = [
        ProviderSettings(id="busy-source", name="Busy", kind="openai", base_url="http://busy/v1", model="a"),
        ProviderSettings(id="ready-source", name="Ready", kind="openai", base_url="http://ready/v1", model="b", requests_per_minute=3),
    ]
    template = SummaryTemplate(id="available", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")
    used: list[str] = []

    def fake_availability(self, estimated_tokens: int = 1) -> dict[str, int | float | bool]:
        if self.provider.id == "busy-source":
            return {
                "available": False,
                "retry_after_seconds": 0.1,
                "capacity_available": 0,
                "in_flight": 1,
                "requests_in_window": 0,
                "requests_per_minute": 0,
                "tokens_in_window": 0,
                "tokens_per_minute": 0,
                "token_limit_exceeded": False,
            }
        return {
            "available": True,
            "retry_after_seconds": 0.0,
            "capacity_available": 1,
            "in_flight": 0,
            "requests_in_window": 0,
            "requests_per_minute": 3,
            "tokens_in_window": 0,
            "tokens_per_minute": 0,
            "token_limit_exceeded": False,
        }

    async def fake_chat(self, *, system: str, user: str, model: str | None = None, estimated_tokens: int | None = None) -> str:
        used.append(self.provider.id)
        return "summary"

    monkeypatch.setattr(ProviderClient, "availability", fake_availability)
    monkeypatch.setattr(ProviderClient, "chat", fake_chat)
    result = asyncio.run(Summarizer(AppSettings(), sources, template).run("short transcript", language="en", model="a", mode="complete"))

    assert used == ["ready-source"]
    assert result.markdown.endswith("summary\n")


def test_scheduler_skips_source_when_tpm_window_is_full(monkeypatch) -> None:
    sources = [
        ProviderSettings(id="tpm-full", name="TPM full", kind="openai", base_url="http://full/v1", model="a", tokens_per_minute=3000),
        ProviderSettings(id="tpm-ready", name="TPM ready", kind="openai", base_url="http://ready/v1", model="b", tokens_per_minute=10000),
    ]
    template = SummaryTemplate(id="tpm", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")
    used: list[str] = []

    def fake_availability(self, estimated_tokens: int = 1) -> dict[str, int | float | bool]:
        if self.provider.id == "tpm-full":
            return {
                "available": False,
                "retry_after_seconds": 15.0,
                "capacity_available": 1,
                "in_flight": 0,
                "requests_in_window": 0,
                "requests_per_minute": 0,
                "tokens_in_window": 2000,
                "tokens_per_minute": 3000,
                "token_limit_exceeded": False,
            }
        return {
            "available": True,
            "retry_after_seconds": 0.0,
            "capacity_available": 1,
            "in_flight": 0,
            "requests_in_window": 0,
            "requests_per_minute": 0,
            "tokens_in_window": 0,
            "tokens_per_minute": 10000,
            "token_limit_exceeded": False,
        }

    async def fake_chat(self, *, system: str, user: str, model: str | None = None, estimated_tokens: int | None = None) -> str:
        used.append(self.provider.id)
        return "summary"

    monkeypatch.setattr(ProviderClient, "availability", fake_availability)
    monkeypatch.setattr(ProviderClient, "chat", fake_chat)
    result = asyncio.run(Summarizer(AppSettings(), sources, template).run("short transcript", language="en", model="a", mode="complete"))

    assert used == ["tpm-ready"]
    assert result.markdown.endswith("summary\n")


def test_provider_rejects_request_above_hourly_token_limit() -> None:
    provider = ProviderSettings(
        id="tph-small", name="Tiny TPH", kind="openai",
        base_url="http://tph-small/v1", model="a", tokens_per_hour=10,
    )
    with pytest.raises(ProviderError, match="above the 10 TPH limit"):
        asyncio.run(ProviderClient(provider).chat(system="system", user="user", estimated_tokens=11))


def test_progress_reports_request_plan_and_actual_source(monkeypatch) -> None:
    provider = ProviderSettings(id="local", name="Local Ollama", kind="ollama", base_url="http://127.0.0.1:11434", model="llama-test")
    template = SummaryTemplate(id="test", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")
    events = []

    async def fake_chat(self, *, system: str, user: str, model: str | None = None, estimated_tokens: int | None = None) -> str:
        return "note"

    monkeypatch.setattr(ProviderClient, "chat", fake_chat)
    source = "\n\n".join(f"Paragraph {index}: " + "word " * 220 for index in range(2))
    result = asyncio.run(Summarizer(AppSettings(chunk_characters=1000), [provider], template).run(source, language="en", model=provider.model, mode="complete", on_progress=events.append))

    assert result.request_count >= 3
    assert events[0].stage == "summary-plan"
    assert events[0].requests_planned >= 3
    assert any(event.stage == "summary-map" and event.status == "completed" for event in events)
    assert events[-1].stage == "summary-final"
    assert events[-1].requests_completed == events[-1].requests_planned == result.request_count
    assert events[-1].provider_id == provider.id
    assert events[-1].model == provider.model
    started_operations = [event.operation_id for event in events if event.status == "started" and event.operation_id]
    assert len(started_operations) == len(set(started_operations))


def test_progress_keeps_failed_request_visible(monkeypatch) -> None:
    provider = ProviderSettings(id="local", name="Local Ollama", kind="ollama", base_url="http://127.0.0.1:11434", model="llama-test")
    template = SummaryTemplate(id="test", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")
    events = []

    async def failed_chat(self, *, system: str, user: str, model: str | None = None, estimated_tokens: int | None = None) -> str:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(ProviderClient, "chat", failed_chat)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(Summarizer(AppSettings(), [provider], template).run("Short transcript", language="en", model=provider.model, mode="complete", on_progress=events.append))

    assert events[-1].stage == "summary-final"
    assert events[-1].status == "failed"
    assert events[-1].requests_completed == events[-1].requests_planned == 1
