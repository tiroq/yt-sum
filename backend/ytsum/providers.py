from __future__ import annotations

import asyncio
import time
from collections import deque

import httpx

from .keychain import get_secret
from .models import ProviderSettings


class ProviderError(RuntimeError):
    pass


def estimate_chat_tokens(system: str, user: str, max_output_tokens: int) -> int:
    return max(1, (len(system) + len(user) + 3) // 4 + max_output_tokens)


class AsyncRateLimiter:
    def __init__(self, requests_per_minute: int | None, requests_per_hour: int = 0, requests_per_day: int = 0) -> None:
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = max(0, requests_per_hour)
        self.requests_per_day = max(0, requests_per_day)
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self.waiting = 0
        self._next_allowed_at = 0.0

    @property
    def limits(self) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            (name, limit, seconds)
            for name, limit, seconds in (
                ("minute", self.requests_per_minute or 0, 60),
                ("hour", self.requests_per_hour, 3600),
                ("day", self.requests_per_day, 86400),
            )
            if limit
        )

    @property
    def signature(self) -> tuple[int, int, int]:
        return (self.requests_per_minute or 0, self.requests_per_hour, self.requests_per_day)

    def _prune(self, now: float) -> None:
        longest_window = max((seconds for _, _, seconds in self.limits), default=0)
        while longest_window and self._timestamps and now - self._timestamps[0] >= longest_window:
            self._timestamps.popleft()

    @property
    def interval_seconds(self) -> float:
        if not self.requests_per_minute:
            return 0.0
        return 60.0 / self.requests_per_minute

    def count_in_window(self, seconds: int) -> int:
        now = time.monotonic()
        self._prune(now)
        return sum(1 for timestamp in self._timestamps if now - timestamp < seconds)

    def _retry_after_seconds(self, now: float) -> float:
        self._prune(now)
        delays = [max(0.0, self._next_allowed_at - now)] if self.requests_per_minute else []
        for _, limit, seconds in self.limits:
            timestamps = [timestamp for timestamp in self._timestamps if now - timestamp < seconds]
            if len(timestamps) >= limit:
                delays.append(max(0.0, seconds - (now - timestamps[0])))
        return max(delays, default=0.0)

    async def acquire(self) -> None:
        if not self.limits:
            return
        self.waiting += 1
        try:
            while True:
                async with self._lock:
                    now = time.monotonic()
                    delay = self._retry_after_seconds(now)
                    if not delay:
                        self._timestamps.append(now)
                        self._next_allowed_at = now + self.interval_seconds
                        return
                await asyncio.sleep(delay)
        finally:
            self.waiting = max(0, self.waiting - 1)

    def retry_after_seconds(self) -> float:
        now = time.monotonic()
        return self._retry_after_seconds(now)

    def status(self) -> dict[str, int | float | None]:
        now = time.monotonic()
        self._prune(now)
        retry_after = self.retry_after_seconds()
        return {
            "requests_per_minute": self.requests_per_minute,
            "requests_per_hour": self.requests_per_hour,
            "requests_per_day": self.requests_per_day,
            "requests_in_window": self.count_in_window(60),
            "requests_in_hour": self.count_in_window(3600),
            "requests_in_day": self.count_in_window(86400),
            "waiting": self.waiting,
            "retry_after_seconds": round(retry_after, 1),
            "request_interval_seconds": round(self.interval_seconds, 1),
        }


class AsyncTokenRateLimiter:
    def __init__(self, tokens_per_minute: int, tokens_per_hour: int = 0, tokens_per_day: int = 0) -> None:
        self.tokens_per_minute = max(0, tokens_per_minute)
        self.tokens_per_hour = max(0, tokens_per_hour)
        self.tokens_per_day = max(0, tokens_per_day)
        self._events: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()
        self.waiting = 0

    @property
    def limits(self) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            (name, limit, seconds)
            for name, limit, seconds in (
                ("minute", self.tokens_per_minute, 60),
                ("hour", self.tokens_per_hour, 3600),
                ("day", self.tokens_per_day, 86400),
            )
            if limit
        )

    @property
    def signature(self) -> tuple[int, int, int]:
        return (self.tokens_per_minute, self.tokens_per_hour, self.tokens_per_day)

    def _prune(self, now: float) -> None:
        longest_window = max((seconds for _, _, seconds in self.limits), default=0)
        while longest_window and self._events and now - self._events[0][0] >= longest_window:
            self._events.popleft()

    def tokens_in_window(self, seconds: int = 60) -> int:
        now = time.monotonic()
        self._prune(now)
        return sum(tokens for timestamp, tokens in self._events if now - timestamp < seconds)

    def limit_exceeded(self, tokens: int) -> bool:
        return any(tokens > limit for _, limit, _ in self.limits)

    async def acquire(self, tokens: int) -> None:
        if not self.limits:
            return
        exceeded = [(name, limit) for name, limit, _ in self.limits if tokens > limit]
        if exceeded:
            name, limit = min(exceeded, key=lambda item: item[1])
            raise ProviderError(f"Estimated request uses {tokens} tokens, above the {limit} TP{name[0].upper()} limit")
        self.waiting += 1
        try:
            while True:
                async with self._lock:
                    now = time.monotonic()
                    self._prune(now)
                    delays = []
                    for _, limit, seconds in self.limits:
                        used = sum(amount for timestamp, amount in self._events if now - timestamp < seconds)
                        if used + tokens > limit:
                            first_timestamp = next(timestamp for timestamp, _ in self._events if now - timestamp < seconds)
                            delays.append(max(0.0, seconds - (now - first_timestamp)))
                    if not delays:
                        self._events.append((now, tokens))
                        return
                    delay = max(delays)
                await asyncio.sleep(delay)
        finally:
            self.waiting = max(0, self.waiting - 1)

    def retry_after_seconds(self, tokens: int = 1) -> float:
        if not self.limits or self.limit_exceeded(tokens):
            return 0.0
        now = time.monotonic()
        self._prune(now)
        delays = []
        for _, limit, seconds in self.limits:
            window_events = [(timestamp, amount) for timestamp, amount in self._events if now - timestamp < seconds]
            used = sum(amount for _, amount in window_events)
            if used + tokens > limit:
                delays.append(max(0.0, seconds - (now - window_events[0][0])))
        return max(delays, default=0.0)

    def status(self) -> dict[str, int | float]:
        retry_after = self.retry_after_seconds()
        return {
            "tokens_per_minute": self.tokens_per_minute,
            "tokens_per_hour": self.tokens_per_hour,
            "tokens_per_day": self.tokens_per_day,
            "tokens_in_window": self.tokens_in_window(60),
            "tokens_in_hour": self.tokens_in_window(3600),
            "tokens_in_day": self.tokens_in_window(86400),
            "token_waiting": self.waiting,
            "token_retry_after_seconds": round(retry_after, 1),
        }


class AsyncCapacityLimiter:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.semaphore = asyncio.Semaphore(capacity)
        self.waiting = 0

    async def acquire(self) -> None:
        self.waiting += 1
        try:
            await self.semaphore.acquire()
        finally:
            self.waiting = max(0, self.waiting - 1)

    def release(self) -> None:
        self.semaphore.release()

    @property
    def available(self) -> int:
        return max(0, self.semaphore._value)


class ProviderClient:
    _limiters: dict[str, AsyncRateLimiter] = {}
    _token_limiters: dict[str, AsyncTokenRateLimiter] = {}
    _capacity_limiters: dict[str, AsyncCapacityLimiter] = {}
    _activity: dict[str, dict[str, int | str | None]] = {}

    def __init__(self, provider: ProviderSettings) -> None:
        self.provider = provider
        current = self._limiters.get(provider.id)
        request_signature = (provider.requests_per_minute or 0, provider.requests_per_hour, provider.requests_per_day)
        if current is None or current.signature != request_signature:
            current = AsyncRateLimiter(provider.requests_per_minute, provider.requests_per_hour, provider.requests_per_day)
            self._limiters[provider.id] = current
        self.limiter = current
        token_limiter = self._token_limiters.get(provider.id)
        token_signature = (provider.tokens_per_minute, provider.tokens_per_hour, provider.tokens_per_day)
        if token_limiter is None or token_limiter.signature != token_signature:
            token_limiter = AsyncTokenRateLimiter(provider.tokens_per_minute, provider.tokens_per_hour, provider.tokens_per_day)
            self._token_limiters[provider.id] = token_limiter
        self.token_limiter = token_limiter
        capacity = self._capacity_limiters.get(provider.id)
        if capacity is None or capacity.capacity != provider.max_in_flight:
            capacity = AsyncCapacityLimiter(provider.max_in_flight)
            self._capacity_limiters[provider.id] = capacity
        self.capacity_limiter = capacity
        self._activity.setdefault(provider.id, {"in_flight": 0, "completed": 0, "failed": 0, "last_error": None, "consecutive_failures": 0, "cooldown_until": 0.0})

    @classmethod
    def statuses(cls, providers: list[ProviderSettings]) -> list[dict]:
        result = []
        for provider in providers:
            client = cls(provider)
            activity = cls._activity[provider.id]
            cooldown = max(0.0, float(activity["cooldown_until"] or 0) - time.monotonic())
            result.append({
                "id": provider.id,
                "enabled": provider.enabled,
                "max_in_flight": provider.max_in_flight,
                "concurrency_waiting": client.capacity_limiter.waiting,
                "health": "cooldown" if cooldown else ("healthy" if provider.enabled else "paused"),
                "cooldown_seconds": round(cooldown, 1),
                **client.limiter.status(),
                **client.token_limiter.status(),
                **activity,
            })
        return result

    def availability(self, estimated_tokens: int = 1) -> dict[str, int | float | bool]:
        activity = self._activity[self.provider.id]
        cooldown = max(0.0, float(activity["cooldown_until"] or 0) - time.monotonic())
        request_retry_after = self.limiter.retry_after_seconds()
        token_retry_after = self.token_limiter.retry_after_seconds(estimated_tokens)
        capacity_available = self.capacity_limiter.available
        token_limit_exceeded = self.token_limiter.limit_exceeded(estimated_tokens)
        return {
            "available": bool(self.provider.enabled and not cooldown and not request_retry_after and not token_retry_after and not token_limit_exceeded and capacity_available > 0),
            "retry_after_seconds": round(max(cooldown, request_retry_after, token_retry_after), 1),
            "capacity_available": capacity_available,
            "in_flight": int(activity["in_flight"]),
            "requests_in_window": self.limiter.count_in_window(60),
            "requests_in_hour": self.limiter.count_in_window(3600),
            "requests_in_day": self.limiter.count_in_window(86400),
            "requests_per_minute": self.provider.requests_per_minute or 0,
            "requests_per_hour": self.provider.requests_per_hour,
            "requests_per_day": self.provider.requests_per_day,
            "request_interval_seconds": self.limiter.interval_seconds,
            "tokens_in_window": self.token_limiter.tokens_in_window(60),
            "tokens_in_hour": self.token_limiter.tokens_in_window(3600),
            "tokens_in_day": self.token_limiter.tokens_in_window(86400),
            "tokens_per_minute": self.provider.tokens_per_minute,
            "tokens_per_hour": self.provider.tokens_per_hour,
            "tokens_per_day": self.provider.tokens_per_day,
            "token_limit_exceeded": token_limit_exceeded,
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if secret := get_secret(self.provider.id):
            headers["Authorization"] = f"Bearer {secret}"
        return headers

    def _openai_base_url(self) -> str:
        """Accept either an API root or a copied chat-completions URL.

        The settings field normally contains e.g. ``https://api.example/v1``.
        Pasting the full endpoint is common, so remove that final route before
        composing both model-discovery and chat URLs.
        """
        return self.provider.base_url.removesuffix("/chat/completions").rstrip("/")

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
                response = await client.get(f"{self._openai_base_url()}/models", headers=self._headers())
                response.raise_for_status()
                return sorted(item["id"] for item in response.json().get("data", []) if item.get("id"))
        except (httpx.HTTPError, KeyError, ValueError) as error:
            detail = str(error) or type(error).__name__
            raise ProviderError(f"Unable to fetch models from {self.provider.name}: {detail}") from error

    async def chat(self, *, system: str, user: str, model: str | None = None, estimated_tokens: int | None = None) -> str:
        self._assert_privacy()
        if not self.provider.enabled:
            raise ProviderError(f"{self.provider.name} is disabled")
        selected_model = model or self.provider.model
        if not selected_model:
            raise ProviderError(f"No model selected for {self.provider.name}")
        activity = self._activity[self.provider.id]
        cooldown = max(0.0, float(activity["cooldown_until"] or 0) - time.monotonic())
        if cooldown:
            raise ProviderError(f"{self.provider.name} is cooling down for {cooldown:.1f}s")
        tokens = estimated_tokens or estimate_chat_tokens(system, user, self.provider.max_output_tokens)
        await self.token_limiter.acquire(tokens)
        await self.limiter.acquire()
        await self.capacity_limiter.acquire()
        activity["in_flight"] = int(activity["in_flight"]) + 1
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
                        f"{self._openai_base_url()}/chat/completions",
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
            detail = str(error) or type(error).__name__
            activity["failed"] = int(activity["failed"]) + 1
            activity["last_error"] = detail
            activity["consecutive_failures"] = int(activity["consecutive_failures"]) + 1
            retry_after = 0.0
            if isinstance(error, httpx.HTTPStatusError):
                header = error.response.headers.get("Retry-After", "")
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = 0.0
            if int(activity["consecutive_failures"]) >= 3 or retry_after:
                activity["cooldown_until"] = time.monotonic() + max(60.0, retry_after)
            raise ProviderError(f"Summary request failed for {self.provider.name}: {detail}") from error
        finally:
            activity["in_flight"] = max(0, int(activity["in_flight"]) - 1)
            self.capacity_limiter.release()
        if not content or not content.strip():
            activity["failed"] = int(activity["failed"]) + 1
            activity["last_error"] = "Empty response"
            raise ProviderError(f"{self.provider.name} returned an empty response")
        activity["completed"] = int(activity["completed"]) + 1
        activity["last_error"] = None
        activity["consecutive_failures"] = 0
        activity["cooldown_until"] = 0.0
        return content.strip()
