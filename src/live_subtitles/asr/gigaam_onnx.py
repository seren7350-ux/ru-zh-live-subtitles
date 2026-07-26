"""Lazy onnx-asr wrapper for short GigaAM WAV transcription."""

from __future__ import annotations

import importlib
import time
import warnings
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import DEFAULT_ASR_MODEL, DEFAULT_PROVIDER


class AsrError(RuntimeError):
    """Base class for user-facing ASR errors."""


class InvalidAudioFileError(AsrError):
    """Raised when the requested input is not a readable WAV file."""


class ProviderUnavailableError(AsrError):
    """Raised when the requested ONNX Runtime provider is unavailable."""


class ModelLoadError(AsrError):
    """Raised when onnx-asr cannot load the selected model."""


class AudioTranscriptionError(AsrError):
    """Raised when the model cannot recognize the input audio."""


@dataclass(frozen=True)
class RecognitionMetrics:
    audio_duration_seconds: float
    model_load_seconds: float
    recognition_seconds: float
    rtf: float | None


class GigaAMOnnxRecognizer:
    """Recognize short WAV files with one lazily loaded onnx-asr model."""

    def __init__(
        self,
        model_name: str = DEFAULT_ASR_MODEL,
        provider: str = DEFAULT_PROVIDER,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.model_name = model_name
        self.provider = provider
        self._clock = clock
        self._model: Any | None = None
        self._model_load_seconds = 0.0
        self.last_metrics: RecognitionMetrics | None = None

    @staticmethod
    def _validate_wav(path: Path) -> tuple[Path, float]:
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            raise InvalidAudioFileError(f"WAV file does not exist: {resolved}")
        if not resolved.is_file():
            raise InvalidAudioFileError(f"Audio path is not a regular file: {resolved}")
        if resolved.suffix.lower() != ".wav":
            raise InvalidAudioFileError(f"Only .wav files are supported: {resolved}")
        try:
            with wave.open(str(resolved), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                duration = wav_file.getnframes() / frame_rate if frame_rate > 0 else 0.0
        except (OSError, EOFError, wave.Error) as exc:
            raise InvalidAudioFileError(f"Unable to read WAV metadata from {resolved}: {exc}") from exc
        return resolved, duration

    def _validate_provider(self) -> None:
        try:
            onnxruntime = importlib.import_module("onnxruntime")
            available = list(onnxruntime.get_available_providers())
        except Exception as exc:
            raise ProviderUnavailableError(f"Unable to query ONNX Runtime providers: {exc}") from exc
        if self.provider not in available:
            choices = ", ".join(available) or "none"
            raise ProviderUnavailableError(
                f"ONNX Runtime provider {self.provider!r} is unavailable. Available providers: {choices}."
            )

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        self._validate_provider()
        started = self._clock()
        try:
            onnx_asr = importlib.import_module("onnx_asr")
            model = onnx_asr.load_model(self.model_name, providers=[self.provider])
        except Exception as exc:
            raise ModelLoadError(
                f"Unable to load ASR model {self.model_name!r} with provider {self.provider!r}: {exc}"
            ) from exc
        self._model_load_seconds = self._clock() - started
        self._model = model
        return model

    def transcribe_file(self, path: Path) -> str:
        resolved, audio_duration = self._validate_wav(path)
        model = self._load_model()
        started = self._clock()
        try:
            raw_result = model.recognize(resolved)
        except Exception as exc:
            raise AudioTranscriptionError(f"Unable to recognize audio from {resolved}: {exc}") from exc
        recognition_seconds = self._clock() - started
        rtf = recognition_seconds / audio_duration if audio_duration > 0 else None
        self.last_metrics = RecognitionMetrics(
            audio_duration_seconds=audio_duration,
            model_load_seconds=self._model_load_seconds,
            recognition_seconds=recognition_seconds,
            rtf=rtf,
        )
        text = "" if raw_result is None else str(raw_result).strip()
        if not text:
            warnings.warn("The ASR model returned an empty transcription.", RuntimeWarning, stacklevel=2)
        return text
