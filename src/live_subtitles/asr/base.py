"""Backend-neutral speech-recognizer contract and result types."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class AsrError(RuntimeError):
    """Base class for user-facing ASR errors from any backend."""


class InvalidAudioFileError(AsrError):
    """Raised when the requested input is not a readable audio file."""


class ProviderUnavailableError(AsrError):
    """Raised when a requested runtime provider is unavailable."""


class ModelLoadError(AsrError):
    """Raised when an ASR backend cannot load its selected model."""


class AudioTranscriptionError(AsrError):
    """Raised when an ASR backend cannot recognize the input audio."""


@dataclass(frozen=True)
class RecognitionMetrics:
    """Timing values shared by short-file ASR backends."""

    audio_duration_seconds: float
    model_load_seconds: float
    recognition_seconds: float
    rtf: float | None


@runtime_checkable
class SpeechRecognizer(Protocol):
    """Lifecycle required by file and live-segment pipelines."""

    model_name: str
    provider: str
    model_load_count: int
    last_metrics: RecognitionMetrics | None

    @property
    def model_load_seconds(self) -> float:
        """Return the one-time backend/model preparation duration."""
        ...

    def prepare(self) -> float:
        """Prepare the backend without opening or recognizing audio."""
        ...

    def transcribe_file(self, path: Path) -> str:
        """Recognize one local audio file and return text."""
        ...
