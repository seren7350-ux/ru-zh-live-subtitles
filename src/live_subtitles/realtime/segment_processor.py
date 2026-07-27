"""Bounded, single-worker ASR/translation processing for completed VAD segments."""

from __future__ import annotations

import queue
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..audio.wav_io import write_pcm16_mono_wav
from ..pipeline.offline_file import (
    OfflineAudioTranslationPipeline,
    PipelineAsrError,
    PipelineTranslationError,
)
from .metrics import TimingAccumulator
from .segmenter import AudioSegment
from .vad_model import SAMPLE_RATE

DEFAULT_SEGMENT_QUEUE_SIZE = 8
MIN_SEGMENT_QUEUE_SIZE = 1
MAX_SEGMENT_QUEUE_SIZE = 32
BACKLOG_MESSAGE = "字幕处理积压，完整语音片段无法入队"
_STOP = object()


class SegmentProcessorError(RuntimeError):
    """Raised when live subtitle infrastructure cannot continue safely."""


class SegmentBacklogError(SegmentProcessorError):
    """Raised when a complete segment would be lost at the queue boundary."""


@dataclass
class QueuedSegment:
    index: int
    segment: AudioSegment
    emitted_at: float
    queued_at: float | None = None
    queued_ready: threading.Event | None = None


@dataclass(frozen=True)
class LiveSubtitleResult:
    index: int
    segment_start_at: float
    segment_end_at: float
    emitted_at: float
    queued_at: float
    processing_started_at: float
    russian_ready_at: float | None
    chinese_ready_at: float | None
    audio_duration_seconds: float
    queue_wait_seconds: float
    asr_seconds: float | None
    translation_seconds: float | None
    processing_seconds: float
    rtf: float | None
    vad_release_latency_seconds: float
    russian_latency_seconds: float | None
    chinese_latency_seconds: float | None
    russian_text: str
    chinese_text: str
    succeeded: bool
    error_stage: str | None
    error: str | None


@dataclass(frozen=True)
class SegmentProcessorMetrics:
    queue_capacity: int
    enqueued_segments: int
    dequeued_segments: int
    queue_high_watermark: int
    queue_final_depth: int
    backlog_failures: int
    successful_segments: int
    failed_segments: int
    temp_files_created: int
    temp_files_deleted: int
    temp_files_remaining: int
    average_queue_wait_seconds: float
    median_queue_wait_seconds: float
    p95_queue_wait_seconds: float
    average_processing_seconds: float
    median_processing_seconds: float
    p95_processing_seconds: float
    average_rtf: float
    median_rtf: float
    p95_rtf: float
    average_russian_latency_seconds: float
    median_russian_latency_seconds: float
    p95_russian_latency_seconds: float
    average_chinese_latency_seconds: float
    median_chinese_latency_seconds: float
    p95_chinese_latency_seconds: float
    retained_results: int
    worker_exited: bool


class SegmentProcessor:
    """Serialize temporary-WAV ASR and translation on one bounded worker."""

    def __init__(
        self,
        pipeline: OfflineAudioTranslationPipeline,
        *,
        queue_size: int = DEFAULT_SEGMENT_QUEUE_SIZE,
        fatal_event: threading.Event | None = None,
        on_result: Callable[[LiveSubtitleResult], None] | None = None,
        clock: Callable[[], float] = time.perf_counter,
        join_timeout: float = 30.0,
        temp_directory: Path | None = None,
    ) -> None:
        if not MIN_SEGMENT_QUEUE_SIZE <= queue_size <= MAX_SEGMENT_QUEUE_SIZE:
            raise SegmentProcessorError(
                f"Segment queue size must be between {MIN_SEGMENT_QUEUE_SIZE} and "
                f"{MAX_SEGMENT_QUEUE_SIZE}."
            )
        if join_timeout <= 0:
            raise SegmentProcessorError("Segment worker join timeout must be greater than zero.")
        self.pipeline = pipeline
        self.queue_size = queue_size
        self.fatal_event = fatal_event or threading.Event()
        self.on_result = on_result
        self._clock = clock
        self.join_timeout = join_timeout
        self.temp_directory = temp_directory
        self._queue: queue.Queue[object] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._worker_exited = threading.Event()
        self._next_index = 1
        self._accepting = False
        self._fatal_error: str | None = None
        self._results: deque[LiveSubtitleResult] = deque(maxlen=8_192)
        self._successful = 0
        self._failed = 0
        self._enqueued = 0
        self._dequeued = 0
        self._high_watermark = 0
        self._backlog_failures = 0
        self._temp_created = 0
        self._temp_deleted = 0
        self._temp_paths: set[Path] = set()
        self._queue_waits = TimingAccumulator()
        self._processing_times = TimingAccumulator()
        self._rtfs = TimingAccumulator()
        self._russian_latencies = TimingAccumulator()
        self._chinese_latencies = TimingAccumulator()

    @property
    def results(self) -> tuple[LiveSubtitleResult, ...]:
        return tuple(self._results)

    @property
    def fatal_error(self) -> str | None:
        return self._fatal_error

    def start(self) -> None:
        if self._thread is not None:
            raise SegmentProcessorError("Segment worker has already been started.")
        self._accepting = True
        self._thread = threading.Thread(
            target=self._worker,
            name="live-subtitle-worker",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, _vad_index: int, segment: AudioSegment) -> None:
        """Put one complete immutable segment without blocking the VAD worker."""

        if not self._accepting:
            raise SegmentProcessorError("Segment worker is not accepting speech segments.")
        emitted_at = self._clock()
        item = QueuedSegment(
            index=self._next_index,
            segment=segment,
            emitted_at=emitted_at,
            queued_ready=threading.Event(),
        )
        try:
            self._queue.put_nowait(item)
        except queue.Full as exc:
            self._backlog_failures += 1
            self._fatal_error = BACKLOG_MESSAGE
            self.fatal_event.set()
            raise SegmentBacklogError(BACKLOG_MESSAGE) from exc
        item.queued_at = self._clock()
        assert item.queued_ready is not None
        item.queued_ready.set()
        self._next_index += 1
        self._enqueued += 1
        self._high_watermark = max(self._high_watermark, self._queue.qsize())

    def _temp_wav(self, segment: AudioSegment) -> Path:
        try:
            temporary = tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="ru-zh-live-subtitles-",
                suffix=".wav",
                dir=self.temp_directory,
                delete=False,
            )
            path = Path(temporary.name)
            temporary.close()
        except Exception as exc:
            raise SegmentProcessorError(
                "Unable to create a temporary speech WAV in the system temp directory."
            ) from exc
        self._temp_created += 1
        self._temp_paths.add(path)
        try:
            write_pcm16_mono_wav(path, segment.samples, sample_rate=SAMPLE_RATE)
        except Exception as exc:
            self._delete_temp(path)
            raise SegmentProcessorError(f"Unable to create temporary PCM16 WAV: {exc}") from exc
        return path

    def _delete_temp(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise SegmentProcessorError("Unable to delete a temporary speech WAV.") from exc
        self._temp_paths.discard(path)
        self._temp_deleted += 1

    def _result_for_error(
        self,
        item: QueuedSegment,
        processing_started: float,
        stage: str,
        error: Exception,
        *,
        russian_text: str = "",
        russian_ready_at: float | None = None,
        asr_seconds: float | None = None,
    ) -> LiveSubtitleResult:
        assert item.queued_at is not None
        finished = self._clock()
        duration = item.segment.duration_seconds
        processing = max(0.0, finished - processing_started)
        return LiveSubtitleResult(
            index=item.index,
            segment_start_at=item.segment.started_at,
            segment_end_at=item.segment.ended_at,
            emitted_at=item.emitted_at,
            queued_at=item.queued_at,
            processing_started_at=processing_started,
            russian_ready_at=russian_ready_at,
            chinese_ready_at=None,
            audio_duration_seconds=duration,
            queue_wait_seconds=max(0.0, processing_started - item.queued_at),
            asr_seconds=asr_seconds,
            translation_seconds=None,
            processing_seconds=processing,
            rtf=processing / duration if duration > 0 else None,
            vad_release_latency_seconds=max(0.0, item.emitted_at - item.segment.ended_at),
            russian_latency_seconds=(
                max(0.0, russian_ready_at - item.segment.ended_at)
                if russian_ready_at is not None
                else None
            ),
            chinese_latency_seconds=None,
            russian_text=russian_text,
            chinese_text="",
            succeeded=False,
            error_stage=stage,
            error=str(error),
        )

    def _process(self, item: QueuedSegment) -> LiveSubtitleResult:
        assert item.queued_at is not None
        processing_started = self._clock()
        path: Path | None = None
        russian_text = ""
        russian_ready: float | None = None
        asr_seconds: float | None = None
        result: LiveSubtitleResult | None = None
        try:
            path = self._temp_wav(item.segment)
            try:
                russian_text, asr_metrics = self.pipeline.transcribe_file(path)
            except PipelineAsrError as exc:
                result = self._result_for_error(item, processing_started, "asr", exc)
            else:
                russian_ready = self._clock()
                asr_seconds = float(asr_metrics.recognition_seconds)
                try:
                    chinese_text, translation_metrics = self.pipeline.translate_text(russian_text)
                except PipelineTranslationError as exc:
                    result = self._result_for_error(
                        item,
                        processing_started,
                        "translation",
                        exc,
                        russian_text=russian_text,
                        russian_ready_at=russian_ready,
                        asr_seconds=asr_seconds,
                    )
                else:
                    chinese_ready = self._clock()
                    duration = item.segment.duration_seconds
                    processing = max(0.0, chinese_ready - processing_started)
                    result = LiveSubtitleResult(
                        index=item.index,
                        segment_start_at=item.segment.started_at,
                        segment_end_at=item.segment.ended_at,
                        emitted_at=item.emitted_at,
                        queued_at=item.queued_at,
                        processing_started_at=processing_started,
                        russian_ready_at=russian_ready,
                        chinese_ready_at=chinese_ready,
                        audio_duration_seconds=duration,
                        queue_wait_seconds=max(0.0, processing_started - item.queued_at),
                        asr_seconds=asr_seconds,
                        translation_seconds=float(translation_metrics.translation_seconds),
                        processing_seconds=processing,
                        rtf=processing / duration if duration > 0 else None,
                        vad_release_latency_seconds=max(
                            0.0, item.emitted_at - item.segment.ended_at
                        ),
                        russian_latency_seconds=max(
                            0.0, russian_ready - item.segment.ended_at
                        ),
                        chinese_latency_seconds=max(
                            0.0, chinese_ready - item.segment.ended_at
                        ),
                        russian_text=russian_text,
                        chinese_text=chinese_text,
                        succeeded=True,
                        error_stage=None,
                        error=None,
                    )
        finally:
            if path is not None:
                self._delete_temp(path)
        assert result is not None
        return result

    def _record_result(self, result: LiveSubtitleResult) -> None:
        self._results.append(result)
        if result.succeeded:
            self._successful += 1
        else:
            self._failed += 1
        self._queue_waits.add(result.queue_wait_seconds)
        self._processing_times.add(result.processing_seconds)
        if result.rtf is not None:
            self._rtfs.add(result.rtf)
        if result.russian_latency_seconds is not None:
            self._russian_latencies.add(result.russian_latency_seconds)
        if result.chinese_latency_seconds is not None:
            self._chinese_latencies.add(result.chinese_latency_seconds)
        if self.on_result is not None:
            self.on_result(result)

    def _worker(self) -> None:
        try:
            while True:
                item = self._queue.get()
                try:
                    if item is _STOP:
                        return
                    if not isinstance(item, QueuedSegment):
                        raise SegmentProcessorError(
                            "Segment queue contained an unexpected object."
                        )
                    if item.queued_ready is None or not item.queued_ready.wait(
                        self.join_timeout
                    ):
                        raise SegmentProcessorError(
                            "Segment enqueue timestamp was not finalized."
                        )
                    self._dequeued += 1
                    result = self._process(item)
                    self._record_result(result)
                finally:
                    self._queue.task_done()
        except Exception as exc:
            self._fatal_error = (
                f"Subtitle processing worker failed ({type(exc).__name__}): {exc}"
            )
            self.fatal_event.set()
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
                else:
                    self._queue.task_done()
        finally:
            self._worker_exited.set()

    def finish(self) -> None:
        """Stop accepting, drain complete segments, and join the worker."""

        self._accepting = False
        thread = self._thread
        if thread is None:
            return
        if self._worker_exited.is_set():
            return
        try:
            self._queue.put(_STOP, timeout=self.join_timeout)
        except queue.Full as exc:
            self._fatal_error = "Unable to stop subtitle worker because its queue remained full."
            self.fatal_event.set()
            raise SegmentProcessorError(self._fatal_error) from exc
        thread.join(self.join_timeout)
        if thread.is_alive():
            self._fatal_error = (
                f"Subtitle processing worker did not exit within {self.join_timeout:g} seconds."
            )
            self.fatal_event.set()

    def metrics(self) -> SegmentProcessorMetrics:
        _, queue_average, queue_median, queue_p95, _ = self._queue_waits.summary()
        _, processing_average, processing_median, processing_p95, _ = (
            self._processing_times.summary()
        )
        _, rtf_average, rtf_median, rtf_p95, _ = self._rtfs.summary()
        _, russian_average, russian_median, russian_p95, _ = (
            self._russian_latencies.summary()
        )
        _, chinese_average, chinese_median, chinese_p95, _ = (
            self._chinese_latencies.summary()
        )
        return SegmentProcessorMetrics(
            queue_capacity=self.queue_size,
            enqueued_segments=self._enqueued,
            dequeued_segments=self._dequeued,
            queue_high_watermark=self._high_watermark,
            queue_final_depth=self._queue.qsize(),
            backlog_failures=self._backlog_failures,
            successful_segments=self._successful,
            failed_segments=self._failed,
            temp_files_created=self._temp_created,
            temp_files_deleted=self._temp_deleted,
            temp_files_remaining=len(self._temp_paths),
            average_queue_wait_seconds=queue_average,
            median_queue_wait_seconds=queue_median,
            p95_queue_wait_seconds=queue_p95,
            average_processing_seconds=processing_average,
            median_processing_seconds=processing_median,
            p95_processing_seconds=processing_p95,
            average_rtf=rtf_average,
            median_rtf=rtf_median,
            p95_rtf=rtf_p95,
            average_russian_latency_seconds=russian_average,
            median_russian_latency_seconds=russian_median,
            p95_russian_latency_seconds=russian_p95,
            average_chinese_latency_seconds=chinese_average,
            median_chinese_latency_seconds=chinese_median,
            p95_chinese_latency_seconds=chinese_p95,
            retained_results=len(self._results),
            worker_exited=self._worker_exited.is_set()
            and (self._thread is None or not self._thread.is_alive()),
        )
