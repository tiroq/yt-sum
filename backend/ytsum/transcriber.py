from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

import httpx

from .models import AppSettings, TranscriptSegment

logger = logging.getLogger(__name__)


LINE_RE = re.compile(r"^\[(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?:(?P<speaker>[^:]{1,60}):\s*)?(?P<text>.+)$")


class TranscriptionBridgeError(RuntimeError):
    pass


def parse_native_transcript(content: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for line in content.splitlines():
        match = LINE_RE.match(line.strip())
        if not match:
            continue
        parts = [int(value) for value in match.group("time").split(":")]
        seconds = parts[-1] + (parts[-2] * 60 if len(parts) > 1 else 0) + (parts[-3] * 3600 if len(parts) > 2 else 0)
        segments.append(TranscriptSegment(start=seconds, end=seconds, text=match.group("text").strip(), speaker=match.group("speaker")))
    for index in range(len(segments) - 1):
        segments[index].end = max(segments[index].start, segments[index + 1].start)
    if segments:
        segments[-1].end = segments[-1].start + 5
    return segments


class MeetingTranscriberBridge:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def _diagnostics(self, audio_path: Path) -> dict[str, object]:
        resolved = audio_path.resolve()
        exists = audio_path.exists()
        is_file = audio_path.is_file() if exists else False
        try:
            size = audio_path.stat().st_size if exists else 0
        except OSError as exc:
            size = None
            logger.warning("[transcribe] stat failed for audio %s: %s", audio_path, exc)
        try:
            readable = os.access(audio_path, os.R_OK)
        except OSError as exc:
            readable = False
            logger.warning("[transcribe] os.access check failed for audio %s: %s", audio_path, exc)
        parent = audio_path.parent
        return {
            "audio_path": str(audio_path),
            "resolved": str(resolved),
            "exists": exists,
            "is_file": is_file,
            "size_bytes": size,
            "readable": readable,
            "parent_exists": parent.exists(),
            "parent_is_dir": parent.is_dir(),
            "parent": str(parent),
        }

    def _token(self) -> str:
        path = Path(self.settings.meeting_transcriber_token_file).expanduser()
        if not path.exists():
            raise TranscriptionBridgeError("Meeting Transcriber token not found. Enable Local Automation API in its Advanced settings.")
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise TranscriptionBridgeError("Meeting Transcriber token file is empty")
        return token

    async def health(self) -> dict[str, str | bool | None]:
        """Return a small diagnostic payload without exposing the bearer token."""
        address = self.settings.meeting_transcriber_url.rstrip("/")
        try:
            token = self._token()
            async with httpx.AsyncClient(timeout=1) as client:
                response = await client.get(f"{address}/state", headers={"Authorization": f"Bearer {token}"})
            if response.status_code == 200:
                payload = response.json()
                return {"ready": True, "address": address, "state": str(payload.get("state") or "available"), "reason": None}
            reason = "unauthorized" if response.status_code == 401 else "unavailable"
            return {"ready": False, "address": address, "state": "unavailable", "reason": reason}
        except TranscriptionBridgeError as error:
            reason = "token_missing" if "token not found" in str(error) else "token_invalid"
            return {"ready": False, "address": address, "state": "unavailable", "reason": reason}
        except (OSError, httpx.HTTPError, ValueError):
            return {"ready": False, "address": address, "state": "unavailable", "reason": "unreachable"}

    def _upload_path(self, audio_path: Path) -> Path:
        resolved = audio_path.resolve()
        if not resolved.exists():
            return resolved
        if not any(ch.isspace() for ch in str(resolved)) and not any(ch in str(resolved) for ch in "'\"`$&;|()[]{}<>\\"):
            return resolved

        safe_name = re.sub(r"\s+", "_", resolved.name)
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", safe_name)
        if not safe_name or safe_name in {".", ".."}:
            safe_name = "audio.wav"

        temp_dir = Path(tempfile.mkdtemp(prefix="yt-sum-asr-"))
        safe_path = temp_dir / safe_name
        shutil.copy2(resolved, safe_path)
        logger.warning(
            "[transcribe] copied audio to a no-space temp path before upload: original=%s safe=%s",
            resolved,
            safe_path,
        )
        return safe_path

    async def transcribe(self, audio_path: Path, max_wait_seconds: int = 1800) -> list[TranscriptSegment]:
        diagnostics = self._diagnostics(audio_path)
        logger.info("[transcribe] local audio diagnostics=%s", diagnostics)
        if not diagnostics["exists"]:
            logger.error("[transcribe] audio file missing before upload: %s (resolved=%s)", audio_path, audio_path.resolve())
        if diagnostics["exists"] and not diagnostics["is_file"]:
            logger.error("[transcribe] audio path exists but is not a regular file: %s", audio_path)
        if diagnostics["readable"] is False:
            logger.error("[transcribe] audio file is not readable by this process: %s", audio_path)

        token = self._token()
        upload_path = self._upload_path(audio_path)
        url = f"{self.settings.meeting_transcriber_url.rstrip('/')}/v1/transcribe?include=transcript"
        request_payload = {"path": str(upload_path), "maxWaitSeconds": max_wait_seconds}
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": f"yt-sum-{audio_path.parent.name}-{audio_path.name}"}
        logger.info(
            "[transcribe] POST endpoint=%s idempotency_key=%s request_payload=%s local_diagnostics=%s",
            url,
            headers["Idempotency-Key"],
            request_payload,
            diagnostics,
        )
        async with httpx.AsyncClient(timeout=max_wait_seconds + 30) as client:
            response = await client.post(url, headers=headers, json=request_payload)
        response_headers = getattr(response, "headers", {}) or {}
        logger.info(
            "[transcribe] Meeting Transcriber response: status=%s content_type=%s body_preview=%s",
            response.status_code,
            response_headers.get("content-type"),
            (response.text or "")[:1000],
        )
        if response.status_code == 202:
            raise TranscriptionBridgeError("Native transcription is still running; retry the job shortly")
        if response.status_code != 200:
            raise TranscriptionBridgeError(f"Meeting Transcriber returned HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        if payload.get("state") == "error":
            details = payload.get("error") or "Native transcription failed"
            diagnostic = (
                f"{details} | local_diagnostics={diagnostics} request_payload={request_payload}"
            )
            logger.error(
                "[transcribe] native ASR reported an error: details=%s local_diagnostics=%s request_payload=%s",
                details,
                diagnostics,
                request_payload,
            )
            raise TranscriptionBridgeError(diagnostic)
        content = payload.get("transcript")
        if not content and payload.get("transcriptPath"):
            transcript_path = Path(payload["transcriptPath"])
            if transcript_path.exists():
                content = transcript_path.read_text(encoding="utf-8")
        if not content:
            raise TranscriptionBridgeError("Native transcription completed without transcript text")
        segments = parse_native_transcript(content)
        if not segments:
            raise TranscriptionBridgeError("Native transcript did not contain timestamped segments")
        return segments
