from __future__ import annotations

import re
from pathlib import Path

import httpx

from .models import AppSettings, TranscriptSegment


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

    async def transcribe(self, audio_path: Path, max_wait_seconds: int = 1800) -> list[TranscriptSegment]:
        token = self._token()
        url = f"{self.settings.meeting_transcriber_url.rstrip('/')}/v1/transcribe?include=transcript"
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": f"yt-sum-{audio_path.stat().st_size}-{audio_path.name}"}
        async with httpx.AsyncClient(timeout=max_wait_seconds + 30) as client:
            response = await client.post(url, headers=headers, json={"path": str(audio_path.resolve()), "maxWaitSeconds": max_wait_seconds})
        if response.status_code == 202:
            raise TranscriptionBridgeError("Native transcription is still running; retry the job shortly")
        if response.status_code != 200:
            raise TranscriptionBridgeError(f"Meeting Transcriber returned HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        if payload.get("state") == "error":
            raise TranscriptionBridgeError(payload.get("error") or "Native transcription failed")
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
