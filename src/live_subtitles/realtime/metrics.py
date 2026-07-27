"""Small immutable records and runtime metrics for live microphone VAD."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

BLOCK_SAMPLES = 512
AUDIO_SAMPLE_RATE = 16_000
DEFAULT_TIMING_WINDOW = 8_192


@dataclass(frozen=True)
class AudioBlock:
    """One immutable callback block with an explicit stream sequence number."""

    sequence_number: int
    samples: np.ndarray
    started_at: float
    ended_at: float
    portaudio_status: str = ""

    def __post_init__(self) -> None:
        samples = np.asarray(self.samples, dtype=np.float32)
        if samples.size != BLOCK_SAMPLES:
            raise ValueError(
                f"AudioBlock samples must contain exactly {BLOCK_SAMPLES} mono samples."
            )
        samples = samples.reshape(-1)
        if not np.isfinite(samples).all():
            raise ValueError("AudioBlock samples must be finite.")
        copied = np.ascontiguousarray(samples).copy()
        copied.setflags(write=False)
        object.__setattr__(self, "samples", copied)

    @property
    def duration_seconds(self) -> float:
        return BLOCK_SAMPLES / AUDIO_SAMPLE_RATE

    @property
    def sequence(self) -> int:
        """Compatibility shorthand used by the queue worker."""

        return self.sequence_number

    @property
    def captured_at(self) -> float:
        """The software callback-receipt time, also the approximate block end."""

        return self.ended_at


@dataclass
class CaptureMetrics:
    callbacks: int = 0
    enqueued_blocks: int = 0
    dropped_blocks: int = 0
    queue_high_watermark: int = 0
    portaudio_status_count: int = 0
    portaudio_status_texts: list[str] = field(default_factory=list)

    def record_status(self, text: str) -> None:
        self.portaudio_status_count += 1
        if text and text not in self.portaudio_status_texts:
            self.portaudio_status_texts.append(text)


@dataclass(frozen=True)
class SegmentMetrics:
    index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    sample_count: int
    forced_split: bool


class TimingAccumulator:
    """Bound memory while retaining exact totals and a rolling percentile window."""

    def __init__(self, max_samples: int = DEFAULT_TIMING_WINDOW) -> None:
        if max_samples <= 0:
            raise ValueError("Timing window must retain at least one sample.")
        self.max_samples = max_samples
        self.count = 0
        self.total = 0.0
        self.maximum = 0.0
        self._samples: deque[float] = deque(maxlen=max_samples)

    @property
    def retained_count(self) -> int:
        return len(self._samples)

    def add(self, value: float) -> None:
        if not math.isfinite(value) or value < 0:
            raise ValueError("Timing values must be finite and non-negative.")
        self.count += 1
        self.total += value
        self.maximum = max(self.maximum, value)
        self._samples.append(value)

    def summary(self) -> tuple[float, float, float, float, float]:
        if self.count == 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        return (
            self.total,
            self.total / self.count,
            percentile(self._samples, 50.0),
            percentile(self._samples, 95.0),
            self.maximum,
        )


@dataclass(frozen=True)
class LiveVadMetrics:
    captured_blocks: int
    processed_blocks: int
    enqueued_blocks: int
    dequeued_blocks: int
    dropped_blocks: int
    sequence_gaps: int
    queue_capacity: int
    queue_high_watermark: int
    queue_current_size: int
    queue_final_depth: int
    portaudio_status_count: int
    portaudio_status_texts: tuple[str, ...]
    detected_segments: int
    forced_segments: int
    ignored_short_segments: int
    saved_segments: int
    save_failures: int
    audio_seconds: float
    session_seconds: float
    inference_total_seconds: float
    average_chunk_seconds: float
    median_chunk_seconds: float
    p95_chunk_seconds: float
    maximum_chunk_seconds: float
    average_queue_wait_seconds: float
    median_queue_wait_seconds: float
    p95_queue_wait_seconds: float
    maximum_queue_wait_seconds: float
    model_load_seconds: float
    session_creation_count: int
    worker_exited: bool
    microphone_closed: bool


def percentile(values: Sequence[float], requested: float) -> float:
    if not values:
        return 0.0
    if not 0.0 <= requested <= 100.0:
        raise ValueError("Percentile must be between zero and 100.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * requested / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_timings(values: Sequence[float]) -> tuple[float, float, float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    ordered = sorted(values)
    total = sum(ordered)
    return (
        total,
        total / len(ordered),
        percentile(ordered, 50.0),
        percentile(ordered, 95.0),
        ordered[-1],
    )
