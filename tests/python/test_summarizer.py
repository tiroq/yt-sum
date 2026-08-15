import asyncio

import pytest

from ytsum.models import AppSettings, ProviderSettings, SummaryTemplate
from ytsum.providers import ProviderClient, ProviderError
from ytsum.summarizer import Summarizer, split_text, strip_frontmatter


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


def test_scheduler_retries_a_failed_source_on_another_source(monkeypatch) -> None:
    sources = [
        ProviderSettings(id="offline-retry", name="Offline", kind="openai", base_url="http://offline/v1", model="a"),
        ProviderSettings(id="ready-retry", name="Ready", kind="openai", base_url="http://ready/v1", model="b"),
    ]
    template = SummaryTemplate(id="retry", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")

    async def flaky_chat(self, *, system: str, user: str, model: str | None = None) -> str:
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

    async def fake_chat(self, *, system: str, user: str, model: str | None = None) -> str:
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


def test_progress_reports_request_plan_and_actual_source(monkeypatch) -> None:
    provider = ProviderSettings(id="local", name="Local Ollama", kind="ollama", base_url="http://127.0.0.1:11434", model="llama-test")
    template = SummaryTemplate(id="test", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")
    events = []

    async def fake_chat(self, *, system: str, user: str, model: str | None = None) -> str:
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


def test_progress_keeps_failed_request_visible(monkeypatch) -> None:
    provider = ProviderSettings(id="local", name="Local Ollama", kind="ollama", base_url="http://127.0.0.1:11434", model="llama-test")
    template = SummaryTemplate(id="test", name_ru="Тест", name_en="Test", prompt="Summarize in {language}.")
    events = []

    async def failed_chat(self, *, system: str, user: str, model: str | None = None) -> str:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(ProviderClient, "chat", failed_chat)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(Summarizer(AppSettings(), [provider], template).run("Short transcript", language="en", model=provider.model, mode="complete", on_progress=events.append))

    assert events[-1].stage == "summary-final"
    assert events[-1].status == "failed"
    assert events[-1].requests_completed == events[-1].requests_planned == 1
