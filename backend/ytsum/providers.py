from __future__ import annotations

import asyncio
import time
from collections import deque

import httpx

from .keychain import get_secret
from .models import ProviderSettings


class ProviderError(RuntimeError):
    pass


class AsyncRateLimiter:
    def __init__(self, requests_per_minute: int | None) -> None:
        self.requests_per_minute = requests_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if not self.requests_per_minute:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= 60:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.requests_per_minute:
                    self._timestamps.append(now)
                    return
                await asyncio.sleep(max(0.05, 60 - (now - self._timestamps[0])))


class ProviderClient:
    _limiters: dict[str, AsyncRateLimiter] = {}

    def __init__(self, provider: ProviderSettings) -> None:
        self.provider = provider
        current = self._limiters.get(provider.id)
        if current is None or current.requests_per_minute != provider.requests_per_minute:
            current = AsyncRateLimiter(provider.requests_per_minute)
            self._limiters[provider.id] = current
        self.limiter = current

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if secret := get_secret(self.provider.id):
            headers["Authorization"] = f"Bearer {secret}"
        return headers

    def _assert_privacy(self) -> None:
        if self.provider.remote and not self.provider.remote_confirmed:
            raise ProviderError("Remote provider has not been explicitly approved for transcript upload")

    async def list_models(self) -> list[str]:
        self._assert_privacy()
        await self.limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if self.provider.kind == "ollama":
                    response = await client.get(f"{self.provider.base_url}/api/tags", headers=self._headers())
                    response.raise_for_status()
                    return sorted(model["name"] for model in response.json().get("models", []) if model.get("name"))
                response = await client.get(f"{self.provider.base_url}/models", headers=self._headers())
                response.raise_for_status()
                return sorted(item["id"] for item in response.json().get("data", []) if item.get("id"))
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise ProviderError(f"Unable to fetch models from {self.provider.name}: {error}") from error

    async def chat(self, *, system: str, user: str, model: str | None = None) -> str:
        self._assert_privacy()
        selected_model = model or self.provider.model
        if not selected_model:
            raise ProviderError(f"No model selected for {self.provider.name}")
        await self.limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30)) as client:
                if self.provider.kind == "ollama":
                    response = await client.post(
                        f"{self.provider.base_url}/api/chat",
                        headers=self._headers(),
                        json={
                            "model": selected_model,
                            "stream": False,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                            "options": {"temperature": self.provider.temperature, "num_predict": self.provider.max_output_tokens},
                        },
                    )
                    response.raise_for_status()
                    content = response.json().get("message", {}).get("content", "")
                else:
                    response = await client.post(
                        f"{self.provider.base_url}/chat/completions",
                        headers=self._headers(),
                        json={
                            "model": selected_model,
                            "temperature": self.provider.temperature,
                            "max_tokens": self.provider.max_output_tokens,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        },
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            raise ProviderError(f"Summary request failed for {self.provider.name}: {error}") from error
        if not content or not content.strip():
            raise ProviderError(f"{self.provider.name} returned an empty response")
        return content.strip()

