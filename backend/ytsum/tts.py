from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .models import AppSettings


class TextToSpeechError(RuntimeError):
    pass


def markdown_to_speech(markdown: str) -> str:
    text = re.sub(r"^---[\s\S]*?---\s*", "", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[`*_>#]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class MacSayTTS:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def ready(self) -> bool:
        return shutil.which("say") is not None and shutil.which("afconvert") is not None

    def synthesize(self, text: str, output: Path) -> None:
        if not text:
            raise TextToSpeechError("Nothing to synthesize")
        if not self.ready():
            raise TextToSpeechError("Text-to-Speech needs the macOS 'say' and 'afconvert' commands")
        aiff = output.with_suffix(".aiff")
        command = ["say", "-r", str(self.settings.tts_rate), "-o", str(aiff)]
        if self.settings.tts_voice.strip():
            command.extend(["-v", self.settings.tts_voice.strip()])
        result = subprocess.run(command, input=text, text=True, capture_output=True, check=False, timeout=900)
        if result.returncode:
            raise TextToSpeechError(result.stderr.strip() or "macOS speech synthesis failed")
        result = subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(output)], text=True, capture_output=True, check=False, timeout=120)
        aiff.unlink(missing_ok=True)
        if result.returncode or not output.exists():
            raise TextToSpeechError(result.stderr.strip() or "Could not convert narration to M4A")
