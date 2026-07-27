"""Near-real-time terminal subtitles from VAD-bounded microphone segments."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TRANSLATION_DEVICE,
    DEFAULT_TRANSLATION_ENGINE,
)
from ..pipeline.offline_file import OfflineAudioTranslationPipeline, PipelinePrepareMetrics
from .live_vad import DEFAULT_QUEUE_SIZE, LiveVadResult, LiveVadSession
from .segment_processor import (
    DEFAULT_SEGMENT_QUEUE_SIZE,
    LiveSubtitleResult,
    SegmentProcessor,
    SegmentProcessorMetrics,
)


@dataclass(frozen=True)
class LiveTerminalResult:
    vad: LiveVadResult
    subtitles: tuple[LiveSubtitleResult, ...]
    subtitle_metrics: SegmentProcessorMetrics
    prepare_metrics: PipelinePrepareMetrics
    errors: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        return not self.errors


class LiveTerminalSession:
    """Own one VAD session, one segment queue, and one serial model pipeline."""

    def __init__(
        self,
        *,
        device_index: int | None = None,
        duration: float = 0.0,
        audio_queue_size: int = DEFAULT_QUEUE_SIZE,
        segment_queue_size: int = DEFAULT_SEGMENT_QUEUE_SIZE,
        threshold: float = 0.5,
        negative_threshold: float = 0.35,
        min_silence_ms: int = 600,
        speech_pad_ms: int = 100,
        pre_roll_ms: int = 250,
        min_segment_ms: int = 300,
        max_segment_seconds: float = 15.0,
        asr_model: str = DEFAULT_ASR_MODEL,
        asr_provider: str = DEFAULT_PROVIDER,
        translation_engine: str = DEFAULT_TRANSLATION_ENGINE,
        translation_model: str | None = None,
        translation_device: str = DEFAULT_TRANSLATION_DEVICE,
        num_beams: int = 1,
        max_new_tokens: int = 256,
        on_result: Callable[[LiveSubtitleResult], None] | None = None,
        on_listening: Callable[[], None] | None = None,
        pipeline: OfflineAudioTranslationPipeline | None = None,
        vad: Any | None = None,
        sounddevice_module: Any | None = None,
        clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
        join_timeout: float = 30.0,
    ) -> None:
        self._fatal_event = threading.Event()
        self.pipeline = pipeline or OfflineAudioTranslationPipeline(
            asr_model=asr_model,
            asr_provider=asr_provider,
            translation_engine=translation_engine,
            translation_model=translation_model,
            device=translation_device,
            num_beams=num_beams,
            max_new_tokens=max_new_tokens,
            clock=clock,
        )
        self.processor = SegmentProcessor(
            self.pipeline,
            queue_size=segment_queue_size,
            fatal_event=self._fatal_event,
            on_result=on_result,
            clock=clock,
            join_timeout=join_timeout,
        )
        self.vad_session = LiveVadSession(
            device_index=device_index,
            duration=duration,
            queue_size=audio_queue_size,
            threshold=threshold,
            negative_threshold=negative_threshold,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
            pre_roll_ms=pre_roll_ms,
            min_segment_ms=min_segment_ms,
            max_segment_seconds=max_segment_seconds,
            vad=vad,
            sounddevice_module=sounddevice_module,
            clock=clock,
            sleeper=sleeper,
            join_timeout=join_timeout,
            on_segment=self.processor.enqueue,
            on_listening=on_listening,
            external_fatal_event=self._fatal_event,
        )
        self._prepare_metrics: PipelinePrepareMetrics | None = None

    def prepare(self) -> PipelinePrepareMetrics:
        """Validate VAD/device first, then preload ASR and translation exactly once."""

        self.vad_session.prepare()
        if self._prepare_metrics is None:
            self._prepare_metrics = self.pipeline.prepare()
        return self._prepare_metrics

    def run(self) -> LiveTerminalResult:
        prepare_metrics = self.prepare()
        self.processor.start()
        try:
            vad_result = self.vad_session.run()
        finally:
            self.processor.finish()
        errors = list(vad_result.errors)
        if self.processor.fatal_error and self.processor.fatal_error not in "\n".join(errors):
            errors.append(self.processor.fatal_error)
        return LiveTerminalResult(
            vad=vad_result,
            subtitles=self.processor.results,
            subtitle_metrics=self.processor.metrics(),
            prepare_metrics=prepare_metrics,
            errors=tuple(errors),
        )
