from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .models import AppSettings, ProviderSettings, SummaryTemplate
from .providers import ProviderClient, ProviderError


SYSTEM_PROMPT = "You summarize source material faithfully. Never invent claims, quotes, people, or timestamps. Return Markdown only."


def split_text(text: str, maximum: int, overlap: int = 400) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= maximum:
        return [text]
    chunks: list[str] = []
    start = 0
    separators = ("\n\n", "\n", ". ", " ")
    while start < len(text):
        hard_end = min(len(text), start + maximum)
        end = hard_end
        if hard_end < len(text):
            lower_bound = start + int(maximum * 0.6)
            for separator in separators:
                candidate = text.rfind(separator, lower_bound, hard_end)
                if candidate > start:
                    end = candidate + len(separator)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - min(overlap, end - start - 1))
    return chunks


@dataclass
class SummaryResult:
    markdown: str
    request_count: int
    provider_ids: list[str]
    models: list[str]


@dataclass(frozen=True)
class SummaryProgress:
    stage: str
    message: str
    status: str
    requests_planned: int
    requests_completed: int
    provider_id: str | None = None
    provider_name: str | None = None
    model: str | None = None
    operation_id: str | None = None


class MultiProviderScheduler:
    """Shared least-loaded pool for all concurrent summary jobs.

    A scheduler is shared by jobs using the same provider set. This means three
    queued videos are distributed across three endpoints instead of each job
    starting its own round-robin counter at provider one. Per-provider clients
    still enforce their own RPM limit; a busy/limited endpoint is skipped while
    other endpoints receive the next available request.
    """
    _shared: dict[tuple[tuple[str, str, str], ...], "MultiProviderScheduler"] = {}
    _shared_lock = asyncio.Lock()

    def __init__(self, providers: list[ProviderSettings]) -> None:
        self.sources = [(provider, ProviderClient(provider)) for provider in providers]
        self._lock = asyncio.Lock()
        self._loads = [0 for _ in self.sources]

    @classmethod
    def shared(cls, providers: list[ProviderSettings]) -> "MultiProviderScheduler":
        key = tuple(sorted((provider.id, provider.base_url, provider.model) for provider in providers))
        scheduler = cls._shared.get(key)
        if scheduler is None:
            scheduler = cls(providers)
            cls._shared[key] = scheduler
        return scheduler

    async def _pick_source(self, excluded: set[str]) -> tuple[int, ProviderSettings, ProviderClient] | None:
        async with self._lock:
            candidates = [index for index, (provider, _) in enumerate(self.sources) if provider.id not in excluded]
            if not candidates:
                return None
            index = min(candidates, key=lambda item: self._loads[item])
            provider, client = self.sources[index]
            self._loads[index] += 1
            return index, provider, client

    async def chat(self, *, system: str, user: str) -> tuple[str, ProviderSettings]:
        excluded: set[str] = set()
        failures: list[str] = []
        while source := await self._pick_source(excluded):
            index, provider, client = source
            try:
                return await client.chat(system=system, user=user, model=provider.model), provider
            except ProviderError as error:
                # A single offline source must not fail an otherwise healthy
                # multi-source job. Retry this request on each remaining one.
                excluded.add(provider.id)
                failures.append(f"{provider.name}: {error}")
            finally:
                async with self._lock:
                    self._loads[index] = max(0, self._loads[index] - 1)
        raise ProviderError("All configured summary sources failed: " + "; ".join(failures))


class Summarizer:
    def __init__(self, settings: AppSettings, providers: list[ProviderSettings], template: SummaryTemplate, pause_waiter=None) -> None:
        self.settings = settings
        if not providers:
            raise ValueError("At least one summary provider is required")
        self.providers = providers
        self.template = template
        self.scheduler = MultiProviderScheduler.shared(providers)
        self.requests = 0
        self.requests_planned = 0
        self.on_progress: Callable[[SummaryProgress], None] | None = None
        self.pause_waiter = pause_waiter

    async def run(self, transcript_markdown: str, *, language: str, model: str, mode: str, on_progress: Callable[[SummaryProgress], None] | None = None) -> SummaryResult:
        self.on_progress = on_progress
        source = strip_frontmatter(transcript_markdown)
        if mode == "cluster":
            self.requests_planned = 1
            self._emit("summary-plan", "Planned 1 final summary request", "started")
            self._emit("summary-source", "Selecting representative transcript passages", "started")
            source = await self._representative_source(source)
            self._emit("summary-source", "Representative transcript passages selected", "completed")
            body = await self._final_summary(source, language, model, lossy=True)
        else:
            chunks = split_text(source, self.settings.chunk_characters)
            self.requests_planned = (len(chunks) + 1) if len(chunks) > 1 else 1
            self._emit("summary-plan", f"Planned {self.requests_planned} request(s)", "started")
            body = await self._map_reduce(source, language, model)
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        frontmatter = (
            "---\n"
            f"providers: {', '.join(provider.id for provider in self.providers)}\n"
            f"models: {', '.join(provider.model for provider in self.providers)}\n"
            f"template: {self.template.id}\n"
            f"language: {language}\n"
            f"mode: {mode}\n"
            f"generated_at: {generated_at}\n"
            "---\n\n"
        )
        return SummaryResult(markdown=frontmatter + body.strip() + "\n", request_count=self.requests, provider_ids=[provider.id for provider in self.providers], models=[provider.model for provider in self.providers])

    def _emit(self, stage: str, message: str, status: str = "progress", provider: ProviderSettings | None = None, operation_id: str | None = None) -> None:
        if self.on_progress:
            self.on_progress(SummaryProgress(stage, message, status, self.requests_planned, self.requests, provider.id if provider else None, provider.name if provider else None, provider.model if provider else None, operation_id))

    async def _map_reduce(self, source: str, language: str, model: str) -> str:
        chunks = split_text(source, self.settings.chunk_characters)
        if len(chunks) == 1:
            return await self._final_summary(chunks[0], language, model)
        prompts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            prompt = (
                f"Summarize source part {index}/{len(chunks)} in {language}. Preserve every important idea, "
                "qualification, named entity, and timestamp link. This is an intermediate note, not the final answer.\n\n"
                f"SOURCE PART:\n{chunk}"
            )
            prompts.append(prompt)
        mapped = await self._run_bounded(
            prompts,
            model,
            "summary-map",
            lambda index, total: f"Summarizing source part {index}/{total}",
        )

        level = mapped
        while len("\n\n".join(level)) > self.settings.chunk_characters:
            groups = split_text("\n\n---\n\n".join(level), self.settings.chunk_characters, overlap=0)
            self.requests_planned += len(groups)
            self._emit("summary-plan", f"Added {len(groups)} merge request(s) to the plan")
            reduce_prompts = [
                f"Merge these intermediate notes in {language}. Remove duplication but preserve all distinct facts and timestamp links.\n\n{group}"
                for group in groups
            ]
            next_level = await self._run_bounded(
                reduce_prompts,
                model,
                "summary-reduce",
                lambda index, total: f"Merging intermediate notes {index}/{total}",
            )
            level = next_level
        return await self._final_summary("\n\n---\n\n".join(level), language, model)

    async def _run_bounded(
        self,
        prompts: list[str],
        model: str,
        stage: str,
        message,
    ) -> list[str]:
        """Bound per-workflow demand so concurrent videos can share endpoints."""
        queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        for index, prompt in enumerate(prompts):
            queue.put_nowait((index, prompt))
        results = [""] * len(prompts)

        async def worker() -> None:
            while True:
                try:
                    index, prompt = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    results[index] = await self._chat(
                        prompt,
                        model,
                        stage,
                        message(index + 1, len(prompts)),
                    )
                finally:
                    queue.task_done()

        capacity = max(1, sum(provider.max_in_flight for provider in self.providers))
        workers = [asyncio.create_task(worker()) for _ in range(min(len(prompts), capacity))]
        await asyncio.gather(*workers)
        return results

    async def _final_summary(self, source: str, language: str, model: str, lossy: bool = False) -> str:
        instruction = self.template.prompt.format(language=language)
        warning = "The input is a representative sample; explicitly avoid implying exhaustive coverage.\n" if lossy else ""
        return await self._chat(f"{instruction}\n{warning}\nSOURCE:\n{source}", model, "summary-final", "Creating final summary")

    async def _chat(self, prompt: str, model: str, stage: str, message: str) -> str:
        if self.pause_waiter:
            await self.pause_waiter()
        self.requests += 1
        operation_id = f"request-{self.requests}"
        self._emit(stage, message, "started", operation_id=operation_id)
        try:
            response, provider = await self.scheduler.chat(system=SYSTEM_PROMPT, user=prompt)
        except Exception as error:
            self._emit(stage, f"{message} failed: {error}", "failed", operation_id=operation_id)
            raise
        self._emit(stage, f"{message} completed", "completed", provider, operation_id)
        return response

    async def _representative_source(self, source: str) -> str:
        chunks = split_text(source, self.settings.cluster_chunk_characters, overlap=150)
        if len(chunks) <= self.settings.cluster_count:
            return "\n\n---\n\n".join(chunks)
        return await asyncio.to_thread(self._cluster, chunks)

    def _cluster(self, chunks: list[str]) -> str:
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
            from sklearn.cluster import KMeans
        except ImportError as error:
            raise RuntimeError("Cluster mode requires the optional 'cluster' dependencies") from error
        model = SentenceTransformer(self.settings.embedding_model, device=self.settings.embedding_device)
        vectors = model.encode(chunks, normalize_embeddings=True, show_progress_bar=False)
        count = min(self.settings.cluster_count, len(chunks))
        kmeans = KMeans(n_clusters=count, random_state=42, n_init="auto").fit(vectors)
        selected: set[int] = set()
        for centroid in kmeans.cluster_centers_:
            distances = np.linalg.norm(vectors - centroid, axis=1)
            for index in np.argsort(distances)[: self.settings.cluster_samples]:
                selected.add(int(index))
        return "\n\n---\n\n".join(chunks[index] for index in sorted(selected))


def strip_frontmatter(markdown: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", markdown, count=1, flags=re.DOTALL).strip()
