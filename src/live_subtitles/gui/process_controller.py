"""Process-isolated live pipeline controller for a responsive Tk mainloop."""

from __future__ import annotations

import multiprocessing
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Callable

from ..diagnostic_logging import (
    configure_diagnostic_logging,
    diagnostic_logger,
    sanitize_diagnostic_text,
)
from ..pipeline.offline_file import OfflineAudioTranslationPipeline
from ..realtime.live_subtitles import LiveTerminalSession
from ..realtime.vad_model import SileroOnnxVad
from .controller import GuiMetrics, sanitize_message
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
    session_id: str | None = None
    log_filename: str | None = None


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
    """One worker's pipe and single-writer counters, never read by the Tk thread.

    A Queue.get_nowait() can still block while reading a partially written frame.
    The dedicated parent reader below receives frames and exposes only an ordinary
    thread queue to Tk. Each side closes its unused pipe endpoint after spawn, so
    killing the writer also releases a reader waiting for the remainder of a frame.
    """

    def __init__(self, context: Any, capacity: int = 256) -> None:
        self.capacity = capacity
        self.reader, self.writer = context.Pipe(duplex=False)
        # Each counter has a single writer: the worker writes enqueue/overflow/HWM
        # and the GUI writes dequeue.  Raw values avoid an abandoned process-shared
        # lock freezing Tk after a worker exits on Windows.
        self.enqueued = context.RawValue("L", 0)
        self.dequeued = context.RawValue("L", 0)
        self.high_watermark = context.RawValue("L", 0)
        self.overflow_count = context.RawValue("L", 0)
        self._send_lock = threading.Lock()

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state.pop("_send_lock")
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        # This lock belongs to this process only. A killed worker cannot leave
        # a lock held in Tk, and concurrent worker callbacks cannot interleave
        # Connection.send frames or corrupt the single-writer counters.
        self._send_lock = threading.Lock()

    def put(self, event: Any) -> bool:
        with self._send_lock:
            if self.enqueued.value - self.dequeued.value >= self.capacity:
                self.overflow_count.value += 1
                return False
            # Publish the count before the frame: the receiver can consume a
            # small message before send() returns in the worker.
            self.enqueued.value += 1
            depth = self.enqueued.value - self.dequeued.value
            self.high_watermark.value = max(self.high_watermark.value, depth)
            self.writer.send(event)
            return True

    def put_summary(self, summary: LiveWorkerSummary) -> None:
        # There is one reserved parent inbox slot for the final summary.
        with self._send_lock:
            self.writer.send(summary)

    def close(self) -> None:
        self.reader.close()
        self.writer.close()


class ProcessStopSignal:
    """Idempotent stop flag with no cross-process synchronization lock."""

    def __init__(self, context: Any) -> None:
        self._flag = context.RawValue("b", 0)
        self._dump_requested = context.RawValue("b", 0)

    def request_diagnostics(self) -> None:
        self._dump_requested.value = 1

    def set(self) -> None:
        self._flag.value = 1

    def is_set(self) -> bool:
        return bool(self._flag.value)

    def wait(self) -> None:
        # Only the worker's daemon forwarder waits. Tk just writes the byte,
        # including after a worker is terminated inside a native call.
        while not self.is_set():
            if self._dump_requested.value:
                self._dump_requested.value = 0
                from ..fault_diagnostics import dump_threads
                dump_threads()
            time.sleep(0.025)


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
        self._inbox: queue.Queue[Any] = queue.Queue(maxsize=self.capacity + 1)
        self._reader_thread: threading.Thread | None = None
        self._reader_finished = threading.Event()
        self._discarded = threading.Event()
        self._receive_error: str | None = None
        self.terminal_seen = False
        self.fatal_seen = False
        self.stop_reason: str | None = None

    def start_receiver(self) -> None:
        """Call only after spawn has copied both endpoints into the worker."""

        self.transport.writer.close()
        self._reader_thread = threading.Thread(
            target=self._receive,
            name="subtitle-overlay-event-reader",
            daemon=True,
        )
        try:
            self._reader_thread.start()
        except BaseException:
            self.transport.reader.close()
            self._reader_finished.set()
            raise

    def _receive(self) -> None:
        try:
            while not self._discarded.is_set():
                item = self.transport.reader.recv()
                if self._discarded.is_set():
                    break
                try:
                    self._inbox.put_nowait(item)
                except queue.Full:
                    # Stop reading on a protocol violation; never buffer or keep
                    # discarding an unbounded stream from a defective producer.
                    self._receive_error = "GUI event receiver capacity exceeded."
                    break
        except EOFError:
            pass
        except Exception as exc:
            self._receive_error = f"GUI event receiver failed: {type(exc).__name__}."
            diagnostic_logger().exception("Worker event pipe receive failed")
        finally:
            self.transport.reader.close()
            self._reader_finished.set()

    @property
    def reader_finished(self) -> bool:
        return self._reader_finished.is_set()

    @property
    def settled(self) -> bool:
        return self.reader_finished and self._inbox.empty()

    def discard(self) -> None:
        """Release an unused inbox without joining a possibly active receiver."""

        self._discarded.set()
        if self._reader_thread is None:
            self.transport.close()
            self._reader_finished.set()

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
        if self._receive_error:
            return self._receive_error
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
                item = self._inbox.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, LiveWorkerSummary):
                self._on_summary(item)
                continue
            events.append(item)
            self.transport.dequeued.value += 1
            if isinstance(item, (StoppedEvent, FatalErrorEvent)):
                self.terminal_seen = True
            if isinstance(item, FatalErrorEvent):
                self.fatal_seen = True
            elif isinstance(item, StoppedEvent):
                self.stop_reason = item.reason
            elif isinstance(item, SessionFinishedEvent):
                self.stop_reason = item.stop_reason
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


class PreparationCancelled(Exception):
    """A normal cancellation at a model preparation boundary."""


def _live_process_main(
    config: LiveWorkerConfig,
    transport: ProcessEventTransport,
    stop_signal: Any,
    session_builder: Callable[..., LiveTerminalSession] = _build_session,
) -> None:
    """Run one unchanged live session outside the Tk process."""

    transport.reader.close()
    logger = configure_diagnostic_logging(
        filename=config.log_filename or f"worker-{os.getppid()}.log",
        session_id=config.session_id,
    )
    logger.info("Worker started; pid=%s; parent_pid=%s", os.getpid(), os.getppid())
    from ..fault_diagnostics import enable_fault_diagnostics, close_fault_diagnostics
    enable_fault_diagnostics("worker")
    stop_thread: threading.Thread | None = None
    session_complete = threading.Event()

    def emit(event: Any) -> None:
        if not transport.put(event):
            stop_signal.set()

    try:
        emit(PreparingEvent("Preparing cached models...", time.perf_counter()))
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
                        start_seconds=getattr(result, "start_seconds", None),
                        end_seconds=getattr(result, "end_seconds", None),
                    )
                )
            else:
                logger.error(
                    "Segment processing failed; index=%s; stage=%s; detail=%s",
                    result.index,
                    result.error_stage or "unknown",
                    result.error or "Segment processing failed.",
                    extra={"sensitive_text": (result.russian_text, result.chinese_text)},
                )
                emit(
                    SegmentErrorEvent(
                        index=result.index,
                        stage=result.error_stage or "unknown",
                        message=sanitize_diagnostic_text(
                            result.error or "Segment processing failed.",
                            sensitive_text=(result.russian_text, result.chinese_text),
                        ),
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
        def preparation_progress(stage: str) -> None:
            if stop_signal.is_set():
                raise PreparationCancelled()
            logger.info("Preparing stage: %s", stage)
            emit(PreparingEvent(f"Preparing {stage}", time.perf_counter()))
        session.preparation_progress = preparation_progress

        def forward_stop() -> None:
            stop_signal.wait()
            if session_complete.is_set():
                return
            logger.info("Worker stop signal received")
            try:
                session.request_stop("GUI requested stop")
            except Exception:
                logger.exception("Worker stop forwarding failed")
            while not session_complete.wait(0.1):
                if getattr(stop_signal, "_dump_requested", None) is not None and stop_signal._dump_requested.value:
                    stop_signal._dump_requested.value = 0
                    from ..fault_diagnostics import dump_threads
                    dump_threads()

        stop_thread = threading.Thread(
            target=forward_stop, name="overlay-stop-forwarder", daemon=True
        )
        stop_thread.start()
        logger.info("Model preparation started")
        prepared = session.prepare()
        if stop_signal.is_set():
            raise PreparationCancelled()
        logger.info("Model preparation finished")
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
        logger.info(
            "Session finished; succeeded=%s; stop_reason=%s; errors=%s",
            result.succeeded, result.vad.stop_reason, len(result.errors),
        )
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
    except PreparationCancelled:
        logger.info("Model preparation cancelled")
        emit(StoppedEvent("Preparation cancelled", time.perf_counter()))
    except Exception as exc:
        logger.exception("Worker session failed")
        try:
            emit(
                FatalErrorEvent(
                    f"{type(exc).__name__}: {sanitize_message(exc)}",
                    time.perf_counter(),
                )
            )
        except (OSError, EOFError):
            logger.exception("Unable to report worker failure to parent")
    finally:
        # Wake the forwarder on a natural finish without reporting a GUI stop.
        session_complete.set()
        stop_signal.set()
        if stop_thread is not None:
            stop_thread.join(timeout=0.2)
        transport.writer.close()
        logger.info("Worker exiting")
        close_fault_diagnostics()


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
        self._logger = diagnostic_logger()
        self._started = False
        self._exit_reported = False
        self._stop_reason: str | None = None
        self._termination_requested = False
        self._kill_requested = False
        self._receiver_failure_reported = False
        self.last_exitcode: int | None = None

    def _accept_summary(self, summary: LiveWorkerSummary) -> None:
        self.last_summary = summary
        self.last_result = summary.result
        self.summaries.append(summary)

    @property
    def running(self) -> bool:
        return self._process is not None and bool(self._process.is_alive())

    @property
    def shutdown_complete(self) -> bool:
        """The worker is gone and all final events/exit diagnostics were consumed."""

        return not self.running and (self._process is None or self._exit_reported)

    def set_device_index(self, device_index: int | None) -> bool:
        """Replace only the next worker's device index while fully stopped."""

        if self.running:
            return False
        self.config = replace(self.config, device_index=device_index)
        return True

    def start(self) -> bool:
        if self.running:
            return False
        if self._process is not None and not self._exit_reported:
            # Keep the old session's final subtitles/summary available to poll.
            return False
        self.dispose()
        self.transport = ProcessEventTransport(self.context)
        self.events = ParentProcessEventQueue(self.transport, self._accept_summary)
        self.metrics.event_queue = self.events  # type: ignore[assignment]
        self.last_summary = None
        self.last_result = None
        self.last_exitcode = None
        self._exit_reported = False
        self._stop_reason = None
        self._termination_requested = False
        self._kill_requested = False
        self._receiver_failure_reported = False
        self.config = replace(
            self.config,
            session_id=uuid.uuid4().hex,
            log_filename=f"worker-{os.getpid()}.log",
        )
        self._stop_signal = ProcessStopSignal(self.context)
        self._process = self.context.Process(
            target=self.process_target,
            args=(self.config, self.transport, self._stop_signal),
            name="subtitle-overlay-live-process",
        )
        try:
            self._process.start()
            self._started = True
            self.events.start_receiver()
        except BaseException:
            self._logger.exception("Worker process startup failed; session=%s", self.config.session_id)
            if self._process.is_alive():
                self._process.terminate()
            self.events.discard()
            self.transport.writer.close()
            if not self._process.is_alive():
                self._process.close()
                self._process = None
            self._exit_reported = True
            raise
        self._logger.info("Worker process started; pid=%s; session=%s", self._process.pid, self.config.session_id)
        return True

    def request_stop(self, reason: str = "user requested stop") -> None:
        if self._stop_signal is not None and self.running:
            if self._stop_reason is None:
                self._stop_reason = reason
                self._logger.info(
                    "Worker stop requested; pid=%s; session=%s; reason=%s",
                    self._process.pid, self.config.session_id, reason,
                )
            self._stop_signal.set()

    def request_diagnostics(self) -> None:
        if self._stop_signal is not None and self.running:
            self._logger.info("Requesting worker thread dump; session=%s", self.config.session_id)
            self._stop_signal.request_diagnostics()

    def poll_process(self) -> tuple[GuiEvent, ...]:
        """Report worker death once, after the receiver has delivered its tail.

        No pipe reads, blocking joins, or synchronization locks run on this path.
        The GUI should drain events before calling this on each timer tick.
        """

        if self._process is None or self._exit_reported:
            return ()
        pending = list(self.events.drain(self.events.capacity + 1))
        if self.running:
            if self.events.fatal_message and not self._receiver_failure_reported:
                self._receiver_failure_reported = True
                self.request_stop("GUI event transport failure")
                pending.append(FatalErrorEvent(self.events.fatal_message, time.perf_counter()))
            return tuple(pending)
        if not self.events.settled:
            return tuple(pending)
        self.last_exitcode = self._process.exitcode
        self._process.join(timeout=0)
        self._exit_reported = True
        self._logger.info(
            "Worker process exited; pid=%s; session=%s; exitcode=%s; stop_reason=%s; forced=%s",
            self._process.pid, self.config.session_id, self.last_exitcode,
            self._stop_reason or self.events.stop_reason or "none",
            self._termination_requested or self._kill_requested,
        )
        if self.last_exitcode != 0 or not self.events.terminal_seen:
            reason = self._stop_reason or "no completion event received"
            message = f"Subtitle worker exited unexpectedly (exitcode={self.last_exitcode}; {reason})."
            self._logger.error(message)
            pending.append(FatalErrorEvent(message, time.perf_counter()))
        elif self.events.fatal_seen or self.events.fatal_message:
            # Preserve the original, more specific error in the GUI.
            if self.events.fatal_message and not self._receiver_failure_reported:
                pending.append(FatalErrorEvent(self.events.fatal_message, time.perf_counter()))
        return tuple(pending)

    def terminate(self) -> None:
        if self.running and not self._termination_requested:
            self._logger.warning("Terminating unresponsive worker; pid=%s; session=%s", self._process.pid, self.config.session_id)
            self._process.terminate()
            self._termination_requested = True

    def kill(self) -> None:
        if self.running and not self._kill_requested:
            self._logger.error("Killing unresponsive worker; pid=%s; session=%s", self._process.pid, self.config.session_id)
            self._process.kill()
            self._kill_requested = True

    def dispose(self) -> None:
        """Release a stopped process; never wait for a live worker or reader."""

        if self.running:
            return
        if self._process is not None:
            if self._started:
                self._process.join(timeout=0)
            self._process.close()
            self._process = None
        self.events.discard()
        self._stop_signal = None
        self._started = False

    def close(self) -> None:
        self.request_stop("window closed")
