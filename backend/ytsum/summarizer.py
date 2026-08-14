from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import AppSettings, ProviderSettings, SummaryTemplate
from .providers import ProviderClient


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


class Summarizer:
    def __init__(self, settings: AppSettings, provider: ProviderSettings, template: SummaryTemplate) -> None:
        self.settings = settings
        self.provider = provider
        self.template = template
        self.client = ProviderClient(provider)
        self.requests = 0

    async def run(self, transcript_markdown: str, *, language: str, model: str, mode: str) -> SummaryResult:
        source = strip_frontmatter(transcript_markdown)
        if mode == "cluster":
            source = await self._representative_source(source)
            body = await self._final_summary(source, language, model, lossy=True)
        else:
            body = await self._map_reduce(source, language, model)
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        frontmatter = (
            "---\n"
            f"provider: {self.provider.id}\n"
            f"model: {model}\n"
            f"template: {self.template.id}\n"
            f"language: {language}\n"
            f"mode: {mode}\n"
            f"generated_at: {generated_at}\n"
            "---\n\n"
        )
        return SummaryResult(markdown=frontmatter + body.strip() + "\n", request_count=self.requests)

    async def _map_reduce(self, source: str, language: str, model: str) -> str:
        chunks = split_text(source, self.settings.chunk_characters)
        if len(chunks) == 1:
            return await self._final_summary(chunks[0], language, model)
        mapped: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            prompt = (
                f"Summarize source part {index}/{len(chunks)} in {language}. Preserve every important idea, "
                "qualification, named entity, and timestamp link. This is an intermediate note, not the final answer.\n\n"
                f"SOURCE PART:\n{chunk}"
            )
            mapped.append(await self._chat(prompt, model))

        level = mapped
        while len("\n\n".join(level)) > self.settings.chunk_characters:
            next_level: list[str] = []
            for group in split_text("\n\n---\n\n".join(level), self.settings.chunk_characters, overlap=0):
                next_level.append(await self._chat(f"Merge these intermediate notes in {language}. Remove duplication but preserve all distinct facts and timestamp links.\n\n{group}", model))
            level = next_level
        return await self._final_summary("\n\n---\n\n".join(level), language, model)

    async def _final_summary(self, source: str, language: str, model: str, lossy: bool = False) -> str:
        instruction = self.template.prompt.format(language=language)
        warning = "The input is a representative sample; explicitly avoid implying exhaustive coverage.\n" if lossy else ""
        return await self._chat(f"{instruction}\n{warning}\nSOURCE:\n{source}", model)

    async def _chat(self, prompt: str, model: str) -> str:
        self.requests += 1
        return await self.client.chat(system=SYSTEM_PROMPT, user=prompt, model=model)

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
