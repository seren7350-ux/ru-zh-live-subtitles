"""Minimal speech-recognizer contract."""

from pathlib import Path
from typing import Protocol


class SpeechRecognizer(Protocol):
    def transcribe_file(self, path: Path) -> str:
        """Recognize one local audio file and return text."""
        ...
