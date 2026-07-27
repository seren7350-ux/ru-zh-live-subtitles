"""Coordinate cached ASR and translation for one short local WAV file."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..asr.gigaam_onnx import AsrError, GigaAMOnnxRecognizer
from ..config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TRANSLATION_DEVICE,
    DEFAULT_TRANSLATION_ENGINE,
)
from ..translation.factory import create_translator
from ..translation.t5_ru_zh import TranslationError


class OfflinePipelineError(RuntimeError):
    """Base class for user-facing offline pipeline errors."""


class PipelineAsrError(OfflinePipelineError):
    """Raised when the ASR stage cannot produce Russian text."""


class PipelineTranslationError(OfflinePipelineError):
    """Raised when the translation stage cannot produce Chinese text."""


@dataclass(frozen=True)
class OfflineTranslationResult:
    audio_path: Path
    russian_text: str
    chinese_text: str
    asr_model: str
    asr_provider: str
    translation_engine: str
    translation_model: str
    audio_duration_seconds: float
    asr_model_load_seconds: float
    asr_seconds: float
    translation_model_load_seconds: float
    translation_seconds: float
    total_processing_seconds: float
    end_to_end_rtf: float | None
    asr_device: str
    translation_device: str
    translation_dtype: str
    peak_cuda_memory_bytes: int


@dataclass(frozen=True)
class PipelinePrepareMetrics:
    asr_prepare_seconds: float
    translation_prepare_seconds: float
    total_prepare_seconds: float


class OfflineAudioTranslationPipeline:
    """Lazily coordinate one reusable ASR instance and one translator instance."""

    def __init__(
        self,
        *,
        asr_model: str = DEFAULT_ASR_MODEL,
        asr_provider: str = DEFAULT_PROVIDER,
        translation_engine: str = DEFAULT_TRANSLATION_ENGINE,
        translation_model: str | None = None,
        device: str = DEFAULT_TRANSLATION_DEVICE,
        num_beams: int = 1,
        max_new_tokens: int = 256,
        recognizer_factory: Callable[..., Any] = GigaAMOnnxRecognizer,
        translator_factory: Callable[..., Any] = create_translator,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.asr_model = asr_model
        self.asr_provider = asr_provider
        self.translation_engine = translation_engine
        self.translation_model = translation_model
        self.device = device
        self.num_beams = num_beams
        self.max_new_tokens = max_new_tokens
        self._recognizer_factory = recognizer_factory
        self._translator_factory = translator_factory
        self._clock = clock
        self._recognizer: Any | None = None
        self._translator: Any | None = None
        self.recognizer_creation_count = 0
        self.translator_creation_count = 0
        self.prepare_metrics: PipelinePrepareMetrics | None = None

    def _get_recognizer(self) -> Any:
        if self._recognizer is None:
            self._recognizer = self._recognizer_factory(
                model_name=self.asr_model,
                provider=self.asr_provider,
            )
            self.recognizer_creation_count += 1
        return self._recognizer

    def _get_translator(self) -> Any:
        if self._translator is None:
            self._translator = self._translator_factory(
                self.translation_engine,
                self.translation_model,
                self.device,
                self.num_beams,
                self.max_new_tokens,
            )
            self.translator_creation_count += 1
        return self._translator

    @property
    def recognizer(self) -> Any:
        return self._get_recognizer()

    @property
    def translator(self) -> Any:
        return self._get_translator()

    def prepare(self) -> PipelinePrepareMetrics:
        """Create and preload exactly one recognizer and translator."""

        if self.prepare_metrics is not None:
            return self.prepare_metrics
        started = self._clock()
        recognizer = self._get_recognizer()
        recognizer.prepare()
        asr_finished = self._clock()
        translator = self._get_translator()
        translator.prepare()
        finished = self._clock()
        self.prepare_metrics = PipelinePrepareMetrics(
            asr_prepare_seconds=asr_finished - started,
            translation_prepare_seconds=finished - asr_finished,
            total_prepare_seconds=finished - started,
        )
        return self.prepare_metrics

    def transcribe_file(self, audio_path: Path) -> tuple[str, Any]:
        try:
            recognizer = self._get_recognizer()
            russian_text = str(recognizer.transcribe_file(audio_path)).strip()
        except OfflinePipelineError:
            raise
        except AsrError as exc:
            raise PipelineAsrError(f"ASR stage failed: {exc}") from exc
        except Exception as exc:
            raise PipelineAsrError(f"ASR stage failed unexpectedly: {exc}") from exc
        metrics = getattr(recognizer, "last_metrics", None)
        if metrics is None:
            raise PipelineAsrError("ASR stage completed without timing metrics.")
        if not russian_text:
            raise PipelineAsrError(
                "ASR stage produced empty Russian text; translation was not started."
            )
        return russian_text, metrics

    def translate_text(self, russian_text: str) -> tuple[str, Any]:
        try:
            translator = self._get_translator()
            chinese_text = str(translator.translate(russian_text)).strip()
        except OfflinePipelineError:
            raise
        except TranslationError as exc:
            raise PipelineTranslationError(f"Translation stage failed: {exc}") from exc
        except Exception as exc:
            raise PipelineTranslationError(f"Translation stage failed unexpectedly: {exc}") from exc
        metrics = getattr(translator, "last_metrics", None)
        if metrics is None:
            raise PipelineTranslationError(
                "Translation stage completed without timing metrics."
            )
        if not chinese_text:
            raise PipelineTranslationError("Translation stage produced empty Chinese text.")
        return chinese_text, metrics

    def run(self, audio_path: Path) -> OfflineTranslationResult:
        """Recognize one WAV locally, then translate its non-empty Russian text."""

        started = self._clock()
        russian_text, asr_metrics = self.transcribe_file(audio_path)
        chinese_text, translation_metrics = self.translate_text(russian_text)
        recognizer = self._get_recognizer()
        translator = self._get_translator()

        total_processing_seconds = self._clock() - started
        audio_duration = float(asr_metrics.audio_duration_seconds)
        end_to_end_rtf = (
            total_processing_seconds / audio_duration if audio_duration > 0 else None
        )
        return OfflineTranslationResult(
            audio_path=audio_path.expanduser().resolve(),
            russian_text=russian_text,
            chinese_text=chinese_text,
            asr_model=str(recognizer.model_name),
            asr_provider=str(recognizer.provider),
            translation_engine=str(translator.engine),
            translation_model=str(translator.model_name),
            audio_duration_seconds=audio_duration,
            asr_model_load_seconds=float(asr_metrics.model_load_seconds),
            asr_seconds=float(asr_metrics.recognition_seconds),
            translation_model_load_seconds=float(translation_metrics.total_load_seconds),
            translation_seconds=float(translation_metrics.translation_seconds),
            total_processing_seconds=total_processing_seconds,
            end_to_end_rtf=end_to_end_rtf,
            asr_device=str(recognizer.provider),
            translation_device=str(translation_metrics.device),
            translation_dtype=str(translation_metrics.dtype),
            peak_cuda_memory_bytes=int(translation_metrics.peak_cuda_memory_bytes),
        )
