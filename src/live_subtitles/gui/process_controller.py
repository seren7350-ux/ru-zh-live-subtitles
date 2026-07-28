"""Process-isolated live pipeline controller for a responsive Tk mainloop."""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from ..pipeline.offline_file import OfflineAudioTranslationPipeline
from ..realtime.live_subtitles import LiveTerminalSession
from ..realtime.vad_model import SileroOnnxVad
from .controller import GuiMetrics, sanitize_message
from .events import (
    FatalErrorEvent,
    ListeningEvent,
    ModelsReadyEvent,
    PreparingEvent,
    SegmentErrorEvent,
    SessionFinishedEvent,
    SessionMetricsSnapshot,
    StoppedEvent,
    SubtitleEvent,
)


@dataclass(frozen=True)
class LiveWorkerConfig:
    device_index: int | None
    duration: float
    audio_queue_size: int
    segment_queue_size: int
    vad_threshold: float
    negative_threshold: float
    min_silence_ms: int
    speech_pad_ms: int
    pre_roll_ms: int
    min_segment_ms: int
    max_segment_seconds: float
    asr_model: str
    asr_provider: str
    translation_engine: str
    translation_model: str | None
    translation_device: str
    num_beams: int
    max_new_tokens: int


@dataclass(frozen=True)
class CompactVadResult:
    metrics: Any
    stop_reason: str


@dataclass(frozen=True)
class CompactLiveResult:
    vad: CompactVadResult
    subtitles: tuple[Any, ...]
    subtitle_metrics: Any
    prepare_metrics: Any
    errors: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class LiveWorkerSummary:
    result: CompactLiveResult
    vad_session_creation_count: int
    asr_model_load_count: int
    translation_tokenizer_load_count: int
    translation_model_load_count: int
    vad_load_seconds: float
    asr_load_seconds: float
    translation_load_seconds: float
    translation_device: str
    translation_dtype: str
    cuda_peak_memory_bytes: int


class ProcessEventTransport:
    """Bounded shared transport with process-safe queue accounting."""

    def __init__(self, context: Any, capacity: int = 256) -> None:
        self.capacity = capacity
        self.queue = context.Queue(maxsize=capacity)
        # Each counter has a single writer: the worker writes enqueue/overflow/HWM
        # and the GUI writes dequeue.  Raw values avoid an abandoned process-shared
        # lock freezing Tk after a worker exits on Windows.
        self.enqueued = context.RawValue("L", 0)
        self.dequeued = context.RawValue("L", 0)
        self.high_watermark = context.RawValue("L", 0)
        self.overflow_count = context.RawValue("L", 0)

    def put(self, event: Any) -> bool:
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            self.overflow_count.value += 1
            return False
        self.enqueued.value += 1
        depth = self.enqueued.value - self.dequeued.value
        self.high_watermark.value = max(self.high_watermark.value, depth)
        return True

    def put_summary(self, summary: LiveWorkerSummary) -> None:
        self.queue.put(summary)


class ParentProcessEventQueue:
    """GuiEventQueue-compatible parent view over a process transport."""

    def __init__(
        self,
        transport: ProcessEventTransport,
        on_summary: Callable[[LiveWorkerSummary], None],
    ) -> None:
        self.transport = transport
        self.capacity = transport.capacity
        self._on_summary = on_summary

    @property
    def enqueued(self) -> int:
        return int(self.transport.enqueued.value)

    @property
    def dequeued(self) -> int:
        return int(self.transport.dequeued.value)

    @property
    def high_watermark(self) -> int:
        return int(self.transport.high_watermark.value)

    @property
    def overflow_count(self) -> int:
        return int(self.transport.overflow_count.value)

    @property
    def fatal_message(self) -> str | None:
        if self.overflow_count:
            return f"GUI event queue overflow ({self.capacity}); the session was stopped."
        return None

    @property
    def size(self) -> int:
        return max(0, self.enqueued - self.dequeued)

    def drain(self, limit: int = 128) -> tuple[Any, ...]:
        events: list[Any] = []
        while len(events) < limit:
            try:
                item = self.transport.queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, LiveWorkerSummary):
                self._on_summary(item)
                continue
            events.append(item)
            self.transport.dequeued.value += 1
        return tuple(events)


def _session_metrics(result: Any) -> SessionMetricsSnapshot:
    vad = result.vad.metrics
    subtitles = result.subtitle_metrics
    return SessionMetricsSnapshot(
        captured_blocks=vad.captured_blocks,
        processed_blocks=vad.processed_blocks,
        detected_segments=vad.detected_segments,
        successful_subtitles=subtitles.successful_segments,
        failed_subtitles=subtitles.failed_segments,
        dropped_blocks=vad.dropped_blocks,
        sequence_gaps=vad.sequence_gaps,
        audio_queue_high_watermark=vad.queue_high_watermark,
        audio_queue_capacity=vad.queue_capacity,
        segment_queue_high_watermark=subtitles.queue_high_watermark,
        segment_queue_capacity=subtitles.queue_capacity,
        microphone_closed=vad.microphone_closed,
        vad_worker_exited=vad.worker_exited,
        subtitle_worker_exited=subtitles.worker_exited,
    )


def _build_session(
    config: LiveWorkerConfig,
    on_result: Callable[[Any], None],
    on_listening: Callable[[], None],
) -> LiveTerminalSession:
    pipeline = OfflineAudioTranslationPipeline(
        asr_model=config.asr_model,
        asr_provider=config.asr_provider,
        translation_engine=config.translation_engine,
        translation_model=config.translation_model,
        device=config.translation_device,
        num_beams=config.num_beams,
        max_new_tokens=config.max_new_tokens,
    )
    return LiveTerminalSession(
        device_index=config.device_index,
        duration=config.duration,
        audio_queue_size=config.audio_queue_size,
        segment_queue_size=config.segment_queue_size,
        threshold=config.vad_threshold,
        negative_threshold=config.negative_threshold,
        min_silence_ms=config.min_silence_ms,
        speech_pad_ms=config.speech_pad_ms,
        pre_roll_ms=config.pre_roll_ms,
        min_segment_ms=config.min_segment_ms,
        max_segment_seconds=config.max_segment_seconds,
        on_result=on_result,
        on_listening=on_listening,
        pipeline=pipeline,
        vad=SileroOnnxVad(),
    )


def _live_process_main(
    config: LiveWorkerConfig,
    transport: ProcessEventTransport,
    stop_signal: Any,
    session_builder: Callable[..., LiveTerminalSession] = _build_session,
) -> None:
    """Run one unchanged live session outside the Tk process."""

    def emit(event: Any) -> None:
        if not transport.put(event):
            stop_signal.set()

    emit(PreparingEvent("Preparing cached models...", time.perf_counter()))
    try:
        session_holder: dict[str, LiveTerminalSession] = {}

        def on_result(result: Any) -> None:
            created = time.perf_counter()
            if result.succeeded:
                emit(
                    SubtitleEvent(
                        index=result.index,
                        russian_text=result.russian_text,
                        chinese_text=result.chinese_text,
                        audio_duration_seconds=result.audio_duration_seconds,
                        russian_latency_seconds=result.russian_latency_seconds,
                        chinese_latency_seconds=result.chinese_latency_seconds,
                        created_at=created,
                    )
                )
            else:
                emit(
                    SegmentErrorEvent(
                        index=result.index,
                        stage=result.error_stage or "unknown",
                        message=sanitize_message(result.error or "Segment processing failed."),
                        created_at=created,
                    )
                )

        def on_listening() -> None:
            session = session_holder["session"]
            device = session.vad_session.device
            emit(
                ListeningEvent(
                    device_name=str(getattr(device, "name", "default input device")),
                    created_at=time.perf_counter(),
                )
            )

        session = session_builder(config, on_result, on_listening)
        session_holder["session"] = session

        def forward_stop() -> None:
            stop_signal.wait()
            session.request_stop("GUI requested stop")

        threading.Thread(target=forward_stop, name="overlay-stop-forwarder", daemon=True).start()
        prepared = session.prepare()
        translator = session.pipeline.translator
        emit(
            ModelsReadyEvent(
                vad_prepare_seconds=float(session.vad_session.vad.load_seconds),
                asr_prepare_seconds=float(prepared.asr_prepare_seconds),
                translation_prepare_seconds=float(prepared.translation_prepare_seconds),
                total_prepare_seconds=float(prepared.total_prepare_seconds),
                translation_device=str(
                    getattr(translator, "actual_device", None)
                    or getattr(translator, "requested_device", "unknown")
                ),
                created_at=time.perf_counter(),
            )
        )
        if stop_signal.is_set():
            session.request_stop("GUI requested stop")
        result = session.run()
        compact = CompactLiveResult(
            vad=CompactVadResult(result.vad.metrics, str(result.vad.stop_reason)),
            subtitles=tuple(result.subtitles),
            subtitle_metrics=result.subtitle_metrics,
            prepare_metrics=result.prepare_metrics,
            errors=tuple(result.errors),
        )
        emit(
            SessionFinishedEvent(
                succeeded=bool(result.succeeded),
                stop_reason=str(result.vad.stop_reason),
                successful_subtitles=int(result.subtitle_metrics.successful_segments),
                failed_subtitles=int(result.subtitle_metrics.failed_segments),
                metrics=_session_metrics(result),
                created_at=time.perf_counter(),
            )
        )
        if result.errors:
            emit(FatalErrorEvent(sanitize_message("; ".join(result.errors)), time.perf_counter()))
        else:
            emit(StoppedEvent(str(result.vad.stop_reason), time.perf_counter()))
        transport.put_summary(
            LiveWorkerSummary(
                result=compact,
                vad_session_creation_count=int(session.vad_session.vad.session_creation_count),
                asr_model_load_count=int(session.pipeline.recognizer.model_load_count),
                translation_tokenizer_load_count=int(translator.tokenizer_load_count),
                translation_model_load_count=int(translator.model_load_count),
                vad_load_seconds=float(session.vad_session.vad.load_seconds),
                asr_load_seconds=float(session.pipeline.recognizer.model_load_seconds),
                translation_load_seconds=float(translator.total_load_seconds),
                translation_device=str(getattr(translator, "actual_device", "unknown")),
                translation_dtype=str(getattr(translator, "dtype", "unknown")),
                cuda_peak_memory_bytes=int(getattr(translator, "peak_cuda_memory_bytes", 0)),
            )
        )
    except Exception as exc:
        emit(
            FatalErrorEvent(
                f"{type(exc).__name__}: {sanitize_message(exc)}",
                time.perf_counter(),
            )
        )
    finally:
        # Release the stop-forwarder normally.  Letting the spawned interpreter
        # tear down a daemon blocked inside multiprocessing.Event.wait() can
        # leave the Windows synchronization primitive unusable by the GUI.
        stop_signal.set()
        transport.queue.close()
        transport.queue.join_thread()


class LiveProcessOverlayController:
    """Start one isolated live-session process and expose GUI controller semantics."""

    def __init__(
        self,
        config: LiveWorkerConfig,
        *,
        context: Any | None = None,
        process_target: Callable[..., None] = _live_process_main,
    ) -> None:
        self.config = config
        self.context = context or multiprocessing.get_context("spawn")
        self.process_target = process_target
        self.transport = ProcessEventTransport(self.context)
        self.last_summary: LiveWorkerSummary | None = None
        self.last_result: CompactLiveResult | None = None
        self.summaries: list[LiveWorkerSummary] = []
        self.events = ParentProcessEventQueue(self.transport, self._accept_summary)
        self.metrics = GuiMetrics(self.events)  # type: ignore[arg-type]
        self._process: Any | None = None
        self._stop_signal: Any | None = None

    def _accept_summary(self, summary: LiveWorkerSummary) -> None:
        self.last_summary = summary
        self.last_result = summary.result
        self.summaries.append(summary)

    @property
    def running(self) -> bool:
        return self._process is not None and bool(self._process.is_alive())

    def set_device_index(self, device_index: int | None) -> bool:
        """Replace only the next worker's device index while fully stopped."""

        if self.running:
            return False
        self.config = replace(self.config, device_index=device_index)
        return True

    def start(self) -> bool:
        if self.running:
            return False
        if self._process is not None:
            self._process.join(timeout=0)
            self._process.close()
        self.last_summary = None
        self.last_result = None
        self._stop_signal = self.context.Event()
        self._process = self.context.Process(
            target=self.process_target,
            args=(self.config, self.transport, self._stop_signal),
            name="subtitle-overlay-live-process",
        )
        self._process.start()
        return True

    def request_stop(self, _reason: str = "user requested stop") -> None:
        if self._stop_signal is not None and self.running:
            self._stop_signal.set()

    def close(self) -> None:
        self.request_stop("window closed")
