"""Exact-format microphone capture with a deliberately minimal callback."""

from __future__ import annotations

import queue
import time
from typing import Any, Callable

import numpy as np

from ..audio.recording import AudioDevice, AudioDeviceError, select_input_device
from .metrics import AudioBlock, CaptureMetrics
from .vad_model import CHUNK_SAMPLES, SAMPLE_RATE

CHANNELS = 1
DTYPE = "float32"
BLOCK_SECONDS = CHUNK_SAMPLES / SAMPLE_RATE


class MicrophoneCaptureError(RuntimeError):
    """Raised when exact live microphone capture cannot be started or continued."""


def _sounddevice() -> Any:
    try:
        import sounddevice
    except Exception as exc:
        raise MicrophoneCaptureError(f"sounddevice is unavailable: {exc}") from exc
    return sounddevice


def validate_live_input_device(
    device_index: int | None,
    *,
    sounddevice_module: Any | None = None,
) -> tuple[Any, AudioDevice]:
    """Select a real input and require native 16 kHz mono float32 support."""

    sd = sounddevice_module or _sounddevice()
    try:
        selected = select_input_device(device_index, sd)
    except AudioDeviceError:
        raise
    try:
        sd.check_input_settings(
            device=selected.index,
            channels=CHANNELS,
            dtype=DTYPE,
            samplerate=SAMPLE_RATE,
        )
    except Exception as exc:
        raise MicrophoneCaptureError(
            f"Input device {selected.index} ({selected.name}) cannot open as mono float32 "
            f"at {SAMPLE_RATE} Hz: {exc}"
        ) from exc
    return sd, selected


class MicrophoneCapture:
    """Own one PortAudio stream and enqueue copied blocks without waiting."""

    def __init__(
        self,
        audio_queue: queue.Queue[object],
        *,
        device: AudioDevice,
        sounddevice_module: Any,
        fatal_event: Any,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.audio_queue = audio_queue
        self.device = device
        self._sd = sounddevice_module
        self._fatal_event = fatal_event
        self._clock = clock
        self.metrics = CaptureMetrics()
        self.fatal_error: str | None = None
        self.stream: Any | None = None
        self.accepting = False
        self.closed = False
        self._next_sequence = 0

    def _fail(self, message: str) -> None:
        if self.fatal_error is None:
            self.fatal_error = message
        self._fatal_event.set()

    def callback(self, indata: Any, frames: int, _time_info: Any, status: Any) -> None:
        """Validate, copy, timestamp, and put_nowait; deliberately nothing else."""

        if not self.accepting:
            return
        self.metrics.callbacks += 1
        status_text = str(status) if status else ""
        if status:
            self.metrics.record_status(status_text)
            if bool(getattr(status, "input_overflow", False)) or "input overflow" in status_text.lower():
                self._fail(f"PortAudio input overflow: {status_text or 'input overflow'}")
                return
        if frames != CHUNK_SAMPLES:
            self._fail(
                f"Unexpected microphone block size: received {frames}, expected {CHUNK_SAMPLES}."
            )
            return
        try:
            array = np.asarray(indata)
            if array.dtype != np.float32:
                raise ValueError(f"dtype {array.dtype}, expected float32")
            if array.ndim != 2 or array.shape != (CHUNK_SAMPLES, CHANNELS):
                raise ValueError(
                    f"shape {array.shape}, expected ({CHUNK_SAMPLES}, {CHANNELS})"
                )
            captured_at = self._clock()
            block = AudioBlock(
                sequence_number=self._next_sequence,
                samples=array[:, 0],
                started_at=captured_at - BLOCK_SECONDS,
                ended_at=captured_at,
                portaudio_status=status_text,
            )
        except Exception as exc:
            self._fail(f"Invalid microphone callback data: {exc}")
            return
        self._next_sequence += 1
        try:
            self.audio_queue.put_nowait(block)
        except queue.Full:
            self.metrics.dropped_blocks += 1
            self._fail(
                f"Audio queue overflow at block {block.sequence}; audio continuity was lost."
            )
            return
        self.metrics.enqueued_blocks += 1
        self.metrics.queue_high_watermark = max(
            self.metrics.queue_high_watermark,
            self.audio_queue.qsize(),
        )

    def start(self) -> None:
        if self.stream is not None:
            raise MicrophoneCaptureError("Microphone stream is already open.")
        try:
            self.stream = self._sd.InputStream(
                device=self.device.index,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=CHUNK_SAMPLES,
                callback=self.callback,
            )
            self.accepting = True
            self.stream.start()
        except Exception as exc:
            self.accepting = False
            self.close()
            raise MicrophoneCaptureError(
                "Unable to start the microphone; check permission, native 16 kHz support, "
                f"and whether device {self.device.index} is busy: {exc}"
            ) from exc

    def close(self) -> None:
        self.accepting = False
        stream, self.stream = self.stream, None
        if stream is None:
            self.closed = True
            return
        errors: list[str] = []
        try:
            stream.stop()
        except Exception as exc:
            errors.append(f"stop failed: {exc}")
        try:
            stream.close()
        except Exception as exc:
            errors.append(f"close failed: {exc}")
        self.closed = True
        if errors:
            self._fail("Microphone cleanup error: " + "; ".join(errors))
