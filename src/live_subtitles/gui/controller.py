"""Background session lifecycle and bounded GUI event transport."""

from __future__ import annotations

import queue
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ..realtime.metrics import TimingAccumulator
from ..realtime.segment_processor import LiveSubtitleResult
from .events import (
    FatalErrorEvent,
    GuiEvent,
    ListeningEvent,
    ModelsReadyEvent,
    PreparingEvent,
    SegmentErrorEvent,
    SessionFinishedEvent,
    SessionMetricsSnapshot,
    StoppedEvent,
    SubtitleEvent,
)

DEFAULT_GUI_QUEUE_SIZE = 256


class GuiControllerError(RuntimeError):
    """Raised when the GUI/session boundary cannot operate safely."""


class LiveSession(Protocol):
    pipeline: Any
    vad_session: Any

    def prepare(self) -> Any: ...

    def run(self) -> Any: ...

    def request_stop(self, reason: str = "user requested stop") -> None: ...


def sanitize_message(error: object) -> str:
    """Remove likely user and temporary paths from a displayed worker error."""

    message = str(error).replace("\r", " ").replace("\n", " ").strip()
    replacements = {
        str(Path.home()): "<home>",
        str(Path(tempfile.gettempdir())): "<temp>",
    }
    for raw, replacement in replacements.items():
        message = re.sub(re.escape(raw), replacement, message, flags=re.IGNORECASE)
    message = re.sub(r"\bhf_[A-Za-z0-9]{8,}\b", "<redacted-token>", message)
    message = re.sub(
        r"\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted-token>", message, flags=re.IGNORECASE
    )
    return message or "Unknown background error."


class GuiEventQueue:
    """A bounded queue that reports overload instead of silently dropping events."""

    def __init__(self, capacity: int = DEFAULT_GUI_QUEUE_SIZE) -> None:
        if not 8 <= capacity <= 4_096:
            raise ValueError("GUI event queue capacity must be between 8 and 4096.")
        self.capacity = capacity
        self._queue: queue.Queue[GuiEvent] = queue.Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self.enqueued = 0
        self.dequeued = 0
        self.high_watermark = 0
        self.overflow_count = 0
        self.fatal_message: str | None = None

    def put(self, event: GuiEvent) -> bool:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self.overflow_count += 1
                self.fatal_message = (
                    f"GUI event queue overflow ({self.capacity}); the session was stopped."
                )
            return False
        with self._lock:
            self.enqueued += 1
            self.high_watermark = max(self.high_watermark, self._queue.qsize())
        return True

    def drain(self, limit: int = 128) -> tuple[GuiEvent, ...]:
        events: list[GuiEvent] = []
        for _ in range(limit):
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
            else:
                self._queue.task_done()
        with self._lock:
            self.dequeued += len(events)
        return tuple(events)

    @property
    def size(self) -> int:
        return self._queue.qsize()


@dataclass(frozen=True)
class GuiMetricsSnapshot:
    events_enqueued: int
    events_dequeued: int
    event_queue_high_watermark: int
    event_queue_capacity: int
    event_queue_final_depth: int
    event_queue_overflows: int
    displayed_subtitles: int
    failed_segments: int
    average_render_latency_seconds: float
    median_render_latency_seconds: float
    p95_render_latency_seconds: float
    maximum_mainloop_delay_seconds: float


class GuiMetrics:
    def __init__(self, event_queue: GuiEventQueue) -> None:
        self.event_queue = event_queue
        self.render_latencies = TimingAccumulator()
        self.mainloop_delays = TimingAccumulator()
        self.displayed_subtitles = 0
        self.failed_segments = 0

    def snapshot(self) -> GuiMetricsSnapshot:
        _, average, median, p95, _ = self.render_latencies.summary()
        _, _, _, _, maximum_delay = self.mainloop_delays.summary()
        return GuiMetricsSnapshot(
            events_enqueued=self.event_queue.enqueued,
            events_dequeued=self.event_queue.dequeued,
            event_queue_high_watermark=self.event_queue.high_watermark,
            event_queue_capacity=self.event_queue.capacity,
            event_queue_final_depth=self.event_queue.size,
            event_queue_overflows=self.event_queue.overflow_count,
            displayed_subtitles=self.displayed_subtitles,
            failed_segments=self.failed_segments,
            average_render_latency_seconds=average,
            median_render_latency_seconds=median,
            p95_render_latency_seconds=p95,
            maximum_mainloop_delay_seconds=maximum_delay,
        )


SessionFactory = Callable[[Callable[[LiveSubtitleResult], None], Callable[[], None]], LiveSession]


class LiveOverlayController:
    """Own one background live session; every UI update is emitted as data."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        event_queue: GuiEventQueue | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.session_factory = session_factory
        self.events = event_queue or GuiEventQueue()
        self.metrics = GuiMetrics(self.events)
        self._clock = clock
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._session: LiveSession | None = None
        self._pending_stop_reason: str | None = None
        self.last_result: Any | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _emit(self, event: GuiEvent) -> None:
        if not self.events.put(event):
            self.request_stop("GUI event queue overflow")

    def _on_result(self, result: LiveSubtitleResult) -> None:
        created = self._clock()
        if result.succeeded:
            self._emit(
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
            self._emit(
                SegmentErrorEvent(
                    index=result.index,
                    stage=result.error_stage or "unknown",
                    message=sanitize_message(result.error or "Segment processing failed."),
                    created_at=created,
                )
            )

    def _on_listening(self) -> None:
        session = self._session
        device = getattr(getattr(session, "vad_session", None), "device", None)
        self._emit(
            ListeningEvent(
                device_name=str(getattr(device, "name", "default input device")),
                created_at=self._clock(),
            )
        )

    @staticmethod
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

    def _run(self) -> None:
        self._emit(PreparingEvent("Preparing cached models...", self._clock()))
        try:
            session = self.session_factory(self._on_result, self._on_listening)
            with self._lock:
                self._session = session
                pending_reason = self._pending_stop_reason
            if pending_reason:
                session.request_stop(pending_reason)
            prepared = session.prepare()
            translator = session.pipeline.translator
            self._emit(
                ModelsReadyEvent(
                    vad_prepare_seconds=float(session.vad_session.vad.load_seconds),
                    asr_prepare_seconds=float(prepared.asr_prepare_seconds),
                    translation_prepare_seconds=float(prepared.translation_prepare_seconds),
                    total_prepare_seconds=float(prepared.total_prepare_seconds),
                    translation_device=str(
                        getattr(translator, "actual_device", None)
                        or getattr(translator, "requested_device", "unknown")
                    ),
                    created_at=self._clock(),
                )
            )
            with self._lock:
                pending_reason = self._pending_stop_reason
            if pending_reason:
                session.request_stop(pending_reason)
            result = session.run()
            self.last_result = result
            self._emit(
                SessionFinishedEvent(
                    succeeded=bool(result.succeeded),
                    stop_reason=str(result.vad.stop_reason),
                    successful_subtitles=int(result.subtitle_metrics.successful_segments),
                    failed_subtitles=int(result.subtitle_metrics.failed_segments),
                    metrics=self._session_metrics(result),
                    created_at=self._clock(),
                )
            )
            if result.errors:
                self._emit(
                    FatalErrorEvent(
                        sanitize_message("; ".join(result.errors)), self._clock()
                    )
                )
            else:
                self._emit(StoppedEvent(str(result.vad.stop_reason), self._clock()))
        except Exception as exc:
            self._emit(
                FatalErrorEvent(
                    f"{type(exc).__name__}: {sanitize_message(exc)}", self._clock()
                )
            )
        finally:
            with self._lock:
                self._session = None

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._pending_stop_reason = None
            self.last_result = None
            thread = threading.Thread(
                target=self._run,
                name="subtitle-overlay-session",
                daemon=True,
            )
            self._thread = thread
        thread.start()
        return True

    def request_stop(self, reason: str = "user requested stop") -> None:
        with self._lock:
            self._pending_stop_reason = self._pending_stop_reason or reason
            session = self._session
        if session is not None:
            session.request_stop(reason)

    def close(self) -> None:
        self.request_stop("window closed")


class DemoOverlayController:
    """Offline visual demo with no microphone, network, or model access."""

    def __init__(
        self,
        *,
        duration: float = 30.0,
        event_queue: GuiEventQueue | None = None,
        clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if duration < 0 or duration > 3_600:
            raise ValueError("Demo duration must be 0 (until stopped) or at most 3600 seconds.")
        self.duration = duration
        self.events = event_queue or GuiEventQueue()
        self.metrics = GuiMetrics(self.events)
        self._clock = clock
        self._sleeper = sleeper
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _emit(self, event: GuiEvent) -> bool:
        accepted = self.events.put(event)
        if not accepted:
            self._stop_event.set()
        return accepted

    def _run(self) -> None:
        started = self._clock()
        self._emit(PreparingEvent("Demo: preparing without models", self._clock()))
        self._sleeper(0.25)
        self._emit(ModelsReadyEvent(0.0, 0.0, 0.0, 0.0, "demo", self._clock()))
        self._emit(ListeningEvent("demo input (microphone is not opened)", self._clock()))
        samples = (
            ("Здравствуйте! Лекция начинается.", "您好！讲座现在开始。"),
            ("Сегодня мы рассмотрим важную тему.", "今天我们将讨论一个重要主题。"),
            ("Пожалуйста, обратите внимание на этот пример.", "请注意这个例子。"),
        )
        index = 0
        error_emitted = False
        next_emit = started
        while not self._stop_event.is_set() and (
            self.duration == 0 or self._clock() - started < self.duration
        ):
            now = self._clock()
            if now >= next_emit:
                russian, chinese = samples[index % len(samples)]
                index += 1
                if not self._emit(
                    SubtitleEvent(index, russian, chinese, 1.5, 0.3, 0.7, now)
                ):
                    break
                next_emit = now + 2.0
                if index >= 2 and not error_emitted:
                    error_emitted = True
                    self._emit(
                        SegmentErrorEvent(
                            index=index + 1,
                            stage="translation",
                            message="demo segment error",
                            created_at=self._clock(),
                        )
                    )
            self._sleeper(0.02)
        reason = "user requested stop" if self._stop_event.is_set() else "demo duration elapsed"
        metrics = SessionMetricsSnapshot(
            captured_blocks=0,
            processed_blocks=0,
            detected_segments=index,
            successful_subtitles=index,
            failed_subtitles=int(error_emitted),
            dropped_blocks=0,
            sequence_gaps=0,
            audio_queue_high_watermark=0,
            audio_queue_capacity=0,
            segment_queue_high_watermark=0,
            segment_queue_capacity=0,
            microphone_closed=True,
            vad_worker_exited=True,
            subtitle_worker_exited=True,
        )
        self._emit(
            SessionFinishedEvent(
                succeeded=True,
                stop_reason=reason,
                successful_subtitles=index,
                failed_subtitles=int(error_emitted),
                metrics=metrics,
                created_at=self._clock(),
            )
        )
        self._emit(StoppedEvent(reason, self._clock()))

    def start(self) -> bool:
        if self.running:
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="subtitle-overlay-demo", daemon=True
        )
        self._thread.start()
        return True

    def request_stop(self, _reason: str = "user requested stop") -> None:
        self._stop_event.set()

    def close(self) -> None:
        self._stop_event.set()
