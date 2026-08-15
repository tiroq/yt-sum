from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from .models import JobRecord, ResourceSnapshot
from .storage import LibraryStorage


@dataclass
class _Resource:
    id: str
    label: str
    capacity: int
    semaphore: asyncio.Semaphore = field(init=False)
    waiting: int = 0
    owners: dict[str, dict[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.semaphore = asyncio.Semaphore(self.capacity)


class ResourceCoordinator:
    """Own in-process resource leases and persist truthful stage states."""

    def __init__(self, storage_provider) -> None:
        self._storage_provider = storage_provider
        self._resources = {
            "yt_dlp": _Resource("yt_dlp", "YouTube / yt-dlp", 1),
            "asr": _Resource("asr", "Meeting Transcriber", 1),
            "tts": _Resource("tts", "Text to speech", 1),
        }

    @property
    def storage(self) -> LibraryStorage:
        return self._storage_provider()

    @asynccontextmanager
    async def stage(
        self,
        job: JobRecord,
        stage: str,
        resource_id: str,
        *,
        progress: float,
        message: str,
        required: bool = True,
    ) -> AsyncIterator[None]:
        resource = self._resources[resource_id]
        waiting_for = {
            "resource_id": resource.id,
            "label": resource.label,
            "reason": f"Waiting for {resource.label}",
        }
        self.storage.transition_stage(
            job.id,
            stage,
            "waiting_resource",
            progress=progress,
            waiting_for=waiting_for,
            resource_id=resource_id,
            message=waiting_for["reason"],
            required=required,
        )
        resource.waiting += 1
        acquired = False
        attempt_id: str | None = None
        lease_id: str | None = None
        heartbeat_task: asyncio.Task | None = None
        attempt_state = "failed"
        attempt_error: str | None = None
        try:
            await resource.semaphore.acquire()
            acquired = True
            resource.waiting = max(0, resource.waiting - 1)
            resource.owners[job.id] = {
                "job_id": job.id,
                "workflow_id": job.workflow_id,
                "video_id": job.video_id,
                "stage": stage,
            }
            self.storage.transition_stage(
                job.id,
                stage,
                "running",
                progress=progress,
                resource_id=resource_id,
                message=message,
                required=required,
            )
            attempt_id = self.storage.start_attempt(job.id, stage, resource_id)
            lease_id = self.storage.acquire_resource_lease(
                attempt_id,
                resource_id,
                job.workflow_id,
                job.video_id,
                self._lease_expiry(),
            )
            heartbeat_task = asyncio.create_task(
                self._heartbeat(attempt_id, lease_id),
                name=f"yt-sum-heartbeat-{attempt_id}",
            )
            yield
        except asyncio.CancelledError:
            attempt_state = "cancelled"
            attempt_error = "Cancelled by user"
            self.storage.transition_stage(
                job.id,
                stage,
                "cancelled",
                progress=progress,
                resource_id=resource_id,
                message="Cancelled",
                error="Cancelled by user",
                required=required,
            )
            raise
        except Exception as error:
            attempt_state = "failed"
            attempt_error = str(error)
            self.storage.transition_stage(
                job.id,
                stage,
                "failed",
                progress=progress,
                resource_id=resource_id,
                message=str(error),
                error=str(error),
                required=required,
            )
            raise
        else:
            attempt_state = "succeeded"
            self.storage.transition_stage(
                job.id,
                stage,
                "succeeded",
                progress=progress,
                resource_id=resource_id,
                message=f"{message} completed",
                required=required,
            )
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            if attempt_id and lease_id:
                self.storage.finish_attempt(attempt_id, lease_id, attempt_state, attempt_error)
            if not acquired:
                resource.waiting = max(0, resource.waiting - 1)
            if acquired:
                resource.owners.pop(job.id, None)
                resource.semaphore.release()

    @staticmethod
    def _lease_expiry() -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat().replace("+00:00", "Z")

    async def _heartbeat(self, attempt_id: str, lease_id: str) -> None:
        while True:
            await asyncio.sleep(5)
            self.storage.heartbeat_attempt(attempt_id, lease_id, self._lease_expiry())

    @asynccontextmanager
    async def external(self, resource_id: str, owner_id: str, label: str) -> AsyncIterator[None]:
        """Serialize non-workflow operations such as playlist inventory."""
        resource = self._resources[resource_id]
        resource.waiting += 1
        acquired = False
        try:
            await resource.semaphore.acquire()
            acquired = True
            resource.waiting = max(0, resource.waiting - 1)
            resource.owners[owner_id] = {
                "job_id": owner_id,
                "workflow_id": "",
                "video_id": "",
                "stage": label,
            }
            yield
        finally:
            if not acquired:
                resource.waiting = max(0, resource.waiting - 1)
            if acquired:
                resource.owners.pop(owner_id, None)
                resource.semaphore.release()

    def snapshots(self) -> list[ResourceSnapshot]:
        return [
            ResourceSnapshot(
                id=resource.id,
                label=resource.label,
                capacity=resource.capacity,
                in_use=len(resource.owners),
                waiting=resource.waiting,
                owners=list(resource.owners.values()),
            )
            for resource in self._resources.values()
        ]
