"""One-session microphone-to-Silero-VAD pipeline with explicit backpressure."""

from __future__ import annotations

import queue
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..audio.recording import AudioDevice
from .metrics import AudioBlock, LiveVadMetrics, TimingAccumulator
from .microphone import MicrophoneCapture, validate_live_input_device
from .segmenter import AudioSegment, VadSegmenter
from .vad_assets import PACKAGE_VERSION
from .vad_model import CHUNK_SAMPLES, SAMPLE_RATE, SileroOnnxVad

DEFAULT_QUEUE_SIZE = 320
MIN_QUEUE_SIZE = 16
MAX_QUEUE_SIZE = 2_000
MAX_DURATION_SECONDS = 3_600.0
_STOP = object()


class LiveVadError(RuntimeError):
    """Raised for invalid live-session configuration or startup."""


@dataclass(frozen=True)
class LiveVadResult:
    device: AudioDevice
    model_version: str
    model_path: Path
    segments: tuple[AudioSegment, ...]
    output_directory: Path | None
    output_paths: tuple[Path, ...]
    metrics: LiveVadMetrics
    stop_reason: str
    errors: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        return not self.errors


def _write_pcm16_atomic(path: Path, samples: np.ndarray) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    pcm = np.rint(np.clip(samples, -1.0, 32767.0 / 32768.0) * 32768.0).astype("<i2")
    try:
        with wave.open(str(temporary), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(pcm.tobytes())
        temporary.replace(path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class LiveVadSession:
    """Coordinate one capture stream, one bounded queue, and one VAD worker."""

    def __init__(
        self,
        *,
        device_index: int | None = None,
        duration: float = 0.0,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        threshold: float = 0.5,
        negative_threshold: float = 0.35,
        min_silence_ms: int = 600,
        speech_pad_ms: int = 100,
        pre_roll_ms: int = 250,
        min_segment_ms: int = 300,
        max_segment_seconds: float = 15.0,
        output_dir: Path | None = None,
        show_probabilities: bool = False,
        vad: SileroOnnxVad | None = None,
        sounddevice_module: Any | None = None,
        clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
        join_timeout: float = 5.0,
        on_segment: Callable[[int, AudioSegment], None] | None = None,
        on_probability: Callable[[int, float], None] | None = None,
    ) -> None:
        if duration < 0 or duration > MAX_DURATION_SECONDS:
            raise LiveVadError(
                f"Duration must be 0 (until Ctrl+C) or at most {MAX_DURATION_SECONDS:g} seconds."
            )
        if not MIN_QUEUE_SIZE <= queue_size <= MAX_QUEUE_SIZE:
            raise LiveVadError(
                f"Queue size must be between {MIN_QUEUE_SIZE} and {MAX_QUEUE_SIZE} blocks."
            )
        if join_timeout <= 0:
            raise LiveVadError("Worker join timeout must be greater than zero.")
        # Construct once here to validate every segmenter option before opening a microphone.
        VadSegmenter(
            threshold=threshold,
            negative_threshold=negative_threshold,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
            pre_roll_ms=pre_roll_ms,
            min_segment_ms=min_segment_ms,
            max_segment_seconds=max_segment_seconds,
        )
        self.device_index = device_index
        self.duration = duration
        self.queue_size = queue_size
        self.threshold = threshold
        self.negative_threshold = negative_threshold
        self.min_silence_ms = min_silence_ms
        self.speech_pad_ms = speech_pad_ms
        self.pre_roll_ms = pre_roll_ms
        self.min_segment_ms = min_segment_ms
        self.max_segment_seconds = max_segment_seconds
        self.output_dir = output_dir
        self.show_probabilities = show_probabilities
        self.vad = vad or SileroOnnxVad()
        self._sd = sounddevice_module
        self._clock = clock
        self._sleeper = sleeper
        self.join_timeout = join_timeout
        self.on_segment = on_segment
        self.on_probability = on_probability
        self.device: AudioDevice | None = None
        self._audio_queue: queue.Queue[object] = queue.Queue(maxsize=queue_size)
        self._fatal_event = threading.Event()
        self._worker_exited = threading.Event()
        self._worker_error: str | None = None
        self._segments: list[AudioSegment] = []
        self._timings = TimingAccumulator()
        self._queue_waits = TimingAccumulator()
        self._processed_blocks = 0
        self._sequence_gaps = 0
        self._ignored_short_segments = 0
        self._prepared = False

    def prepare(self) -> AudioDevice:
        """Validate cached assets and the device without downloading or opening it."""

        if self._prepared:
            assert self.device is not None
            return self.device
        sd, device = validate_live_input_device(
            self.device_index,
            sounddevice_module=self._sd,
        )
        self._sd = sd
        self.vad.prepare()
        if self.vad.model_path is None:
            raise LiveVadError("VAD prepared without exposing a model path.")
        self.device = device
        self._prepared = True
        return device

    def _worker(self) -> None:
        segmenter = VadSegmenter(
            threshold=self.threshold,
            negative_threshold=self.negative_threshold,
            min_silence_ms=self.min_silence_ms,
            speech_pad_ms=self.speech_pad_ms,
            pre_roll_ms=self.pre_roll_ms,
            min_segment_ms=self.min_segment_ms,
            max_segment_seconds=self.max_segment_seconds,
        )
        expected_sequence = 0
        clean_stop = False
        try:
            self.vad.reset()
            while True:
                item = self._audio_queue.get()
                try:
                    if item is _STOP:
                        clean_stop = True
                        break
                    if not isinstance(item, AudioBlock):
                        raise LiveVadError("Audio queue contained an unexpected object.")
                    if item.sequence != expected_sequence:
                        self._sequence_gaps += abs(item.sequence - expected_sequence) or 1
                        raise LiveVadError(
                            f"Audio block sequence gap: expected {expected_sequence}, got {item.sequence}."
                        )
                    expected_sequence += 1
                    started = self._clock()
                    self._queue_waits.add(max(0.0, started - item.captured_at))
                    probability = self.vad.speech_probability(item.samples)
                    elapsed = self._clock() - started
                    self._timings.add(elapsed)
                    self._processed_blocks += 1
                    if self.show_probabilities and self.on_probability is not None:
                        self.on_probability(item.sequence, probability)
                    for segment in segmenter.process(
                        item.samples,
                        probability,
                        item.started_at,
                    ):
                        self._segments.append(segment)
                        if self.on_segment is not None:
                            self.on_segment(len(self._segments), segment)
                finally:
                    self._audio_queue.task_done()
            if clean_stop:
                for segment in segmenter.flush():
                    self._segments.append(segment)
                    if self.on_segment is not None:
                        self.on_segment(len(self._segments), segment)
        except Exception as exc:
            self._worker_error = f"VAD worker failed ({type(exc).__name__}): {exc}"
            self._fatal_event.set()
        finally:
            self._ignored_short_segments = segmenter.ignored_short_segments
            self.vad.reset()
            self._worker_exited.set()

    def _request_worker_stop(self) -> None:
        if self._worker_exited.is_set():
            return
        try:
            self._audio_queue.put(_STOP, timeout=self.join_timeout)
        except queue.Full:
            self._worker_error = (
                self._worker_error
                or "Unable to stop VAD worker because the audio queue remained full."
            )
            self._fatal_event.set()

    def _save_segments(self) -> tuple[Path | None, tuple[Path, ...], list[str]]:
        if self.output_dir is None:
            return None, (), []
        root = self.output_dir.expanduser().resolve()
        session_name = (
            datetime.now(timezone.utc).strftime("session-%Y%m%dT%H%M%S-%fZ-")
            + uuid.uuid4().hex[:8]
        )
        session_dir = root / session_name
        errors: list[str] = []
        paths: list[Path] = []
        try:
            session_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            return session_dir, (), [f"Unable to create segment session directory: {exc}"]
        for index, segment in enumerate(self._segments, start=1):
            path = session_dir / f"segment-{index:04d}.wav"
            try:
                _write_pcm16_atomic(path, segment.samples)
                paths.append(path)
            except Exception as exc:
                errors.append(f"Unable to save {path.name}: {exc}")
        return session_dir, tuple(paths), errors

    def run(self) -> LiveVadResult:
        device = self.prepare()
        assert self._sd is not None
        worker = threading.Thread(target=self._worker, name="live-vad-worker", daemon=True)
        capture = MicrophoneCapture(
            self._audio_queue,
            device=device,
            sounddevice_module=self._sd,
            fatal_event=self._fatal_event,
            clock=self._clock,
        )
        errors: list[str] = []
        stop_reason = "duration elapsed" if self.duration else "stopped"
        session_started = self._clock()
        worker.start()
        try:
            capture.start()
            session_started = self._clock()
            while True:
                if self._fatal_event.is_set():
                    stop_reason = "infrastructure error"
                    break
                if self.duration and self._clock() - session_started >= self.duration:
                    break
                self._sleeper(0.02)
        except KeyboardInterrupt:
            stop_reason = "Ctrl+C"
        except Exception:
            capture.close()
            self._request_worker_stop()
            worker.join(self.join_timeout)
            raise
        finally:
            capture.close()
            self._request_worker_stop()
            worker.join(self.join_timeout)

        session_seconds = self._clock() - session_started
        if worker.is_alive():
            errors.append(
                f"VAD worker did not exit within {self.join_timeout:g} seconds."
            )
            self._fatal_event.set()
        if capture.fatal_error:
            errors.append(capture.fatal_error)
        if self._worker_error:
            errors.append(self._worker_error)
        output_directory: Path | None = None
        output_paths: tuple[Path, ...] = ()
        save_errors: list[str] = []
        if not errors:
            output_directory, output_paths, save_errors = self._save_segments()
            errors.extend(save_errors)

        total, average, median, p95, maximum = self._timings.summary()
        _, queue_average, queue_median, queue_p95, queue_maximum = self._queue_waits.summary()
        metrics = LiveVadMetrics(
            captured_blocks=capture.metrics.enqueued_blocks,
            processed_blocks=self._processed_blocks,
            enqueued_blocks=capture.metrics.enqueued_blocks,
            dequeued_blocks=self._processed_blocks,
            dropped_blocks=capture.metrics.dropped_blocks,
            sequence_gaps=self._sequence_gaps,
            queue_capacity=self.queue_size,
            queue_high_watermark=capture.metrics.queue_high_watermark,
            queue_current_size=self._audio_queue.qsize(),
            queue_final_depth=self._audio_queue.qsize(),
            portaudio_status_count=capture.metrics.portaudio_status_count,
            portaudio_status_texts=tuple(capture.metrics.portaudio_status_texts),
            detected_segments=len(self._segments),
            forced_segments=sum(segment.forced_split for segment in self._segments),
            ignored_short_segments=self._ignored_short_segments,
            saved_segments=len(output_paths),
            save_failures=len(save_errors),
            audio_seconds=self._processed_blocks * CHUNK_SAMPLES / SAMPLE_RATE,
            session_seconds=session_seconds,
            inference_total_seconds=total,
            average_chunk_seconds=average,
            median_chunk_seconds=median,
            p95_chunk_seconds=p95,
            maximum_chunk_seconds=maximum,
            average_queue_wait_seconds=queue_average,
            median_queue_wait_seconds=queue_median,
            p95_queue_wait_seconds=queue_p95,
            maximum_queue_wait_seconds=queue_maximum,
            model_load_seconds=self.vad.load_seconds,
            session_creation_count=self.vad.session_creation_count,
            worker_exited=not worker.is_alive() and self._worker_exited.is_set(),
            microphone_closed=capture.closed,
        )
        assert self.vad.model_path is not None
        return LiveVadResult(
            device=device,
            model_version=PACKAGE_VERSION,
            model_path=self.vad.model_path,
            segments=tuple(self._segments),
            output_directory=output_directory,
            output_paths=output_paths,
            metrics=metrics,
            stop_reason=stop_reason,
            errors=tuple(errors),
        )
