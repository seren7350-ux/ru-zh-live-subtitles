"""Probability-driven segmentation independent of any VAD implementation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AudioSegment:
    samples: np.ndarray
    start_sample: int
    end_sample: int
    started_at: float
    ended_at: float
    forced_split: bool

    def __post_init__(self) -> None:
        copied = np.ascontiguousarray(self.samples, dtype=np.float32)
        copied.setflags(write=False)
        object.__setattr__(self, "samples", copied)

    @property
    def duration_seconds(self) -> float:
        return (self.end_sample - self.start_sample) / 16_000


@dataclass(frozen=True)
class _ChunkRecord:
    start_sample: int
    samples: np.ndarray

    @property
    def end_sample(self) -> int:
        return self.start_sample + self.samples.size


class VadSegmenter:
    """Convert chunk probabilities into immutable, padded speech segments."""

    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        chunk_samples: int = 512,
        threshold: float = 0.5,
        negative_threshold: float = 0.35,
        min_silence_ms: int = 600,
        speech_pad_ms: int = 100,
        pre_roll_ms: int = 250,
        min_segment_ms: int = 300,
        max_segment_seconds: float = 15.0,
    ) -> None:
        if sample_rate != 16_000 or chunk_samples != 512:
            raise ValueError("VadSegmenter currently requires 16 kHz audio and 512-sample chunks.")
        if not 0.0 <= negative_threshold < threshold <= 1.0:
            raise ValueError("VAD thresholds must satisfy 0 <= negative < threshold <= 1.")
        if min_silence_ms <= 0 or speech_pad_ms < 0 or pre_roll_ms < 0:
            raise ValueError("Silence and padding settings must be non-negative.")
        if min_segment_ms <= 0 or max_segment_seconds <= 0:
            raise ValueError("Segment duration settings must be greater than zero.")
        self.sample_rate = sample_rate
        self.chunk_samples = chunk_samples
        self.threshold = threshold
        self.negative_threshold = negative_threshold
        self.min_silence_samples = round(sample_rate * min_silence_ms / 1000)
        self.speech_pad_samples = round(sample_rate * speech_pad_ms / 1000)
        self.pre_roll_samples = round(sample_rate * pre_roll_ms / 1000)
        self.min_segment_samples = round(sample_rate * min_segment_ms / 1000)
        self.max_segment_samples = round(sample_rate * max_segment_seconds)
        self.reset()

    def reset(self) -> None:
        self._pre_roll: deque[_ChunkRecord] = deque()
        self._segment_records: list[_ChunkRecord] = []
        self._active = False
        self._speech_start_sample = 0
        self._last_speech_end_sample = 0
        self._silence_samples = 0
        self._next_sample = 0
        self._stream_origin: float | None = None
        self.ignored_short_segments = 0

    def _trim_pre_roll(self) -> None:
        if self.pre_roll_samples == 0:
            self._pre_roll.clear()
            return
        total = sum(record.samples.size for record in self._pre_roll)
        while self._pre_roll and total > self.pre_roll_samples:
            record = self._pre_roll[0]
            excess = total - self.pre_roll_samples
            if record.samples.size <= excess:
                total -= record.samples.size
                self._pre_roll.popleft()
            else:
                self._pre_roll[0] = _ChunkRecord(
                    record.start_sample + excess,
                    record.samples[excess:].copy(),
                )
                total -= excess

    def _records_after(self, sample: int) -> deque[_ChunkRecord]:
        records: deque[_ChunkRecord] = deque()
        for record in self._segment_records:
            if record.end_sample <= sample:
                continue
            offset = max(0, sample - record.start_sample)
            records.append(
                _ChunkRecord(record.start_sample + offset, record.samples[offset:].copy())
            )
        return records

    def _samples_between(self, start_sample: int, end_sample: int) -> np.ndarray:
        pieces: list[np.ndarray] = []
        for record in self._segment_records:
            if record.end_sample <= start_sample or record.start_sample >= end_sample:
                continue
            left = max(start_sample, record.start_sample) - record.start_sample
            right = min(end_sample, record.end_sample) - record.start_sample
            pieces.append(record.samples[left:right])
        if not pieces:
            return np.empty(0, dtype=np.float32)
        return np.concatenate(pieces).astype(np.float32, copy=False)

    def _finish(self, end_sample: int, *, forced_split: bool) -> AudioSegment | None:
        start_sample = self._segment_records[0].start_sample
        speech_samples = self._last_speech_end_sample - self._speech_start_sample
        samples = self._samples_between(start_sample, end_sample)
        segment: AudioSegment | None = None
        if speech_samples < self.min_segment_samples or samples.size == 0:
            self.ignored_short_segments += 1
        else:
            assert self._stream_origin is not None
            segment = AudioSegment(
                samples=samples,
                start_sample=start_sample,
                end_sample=end_sample,
                started_at=self._stream_origin + start_sample / self.sample_rate,
                ended_at=self._stream_origin + end_sample / self.sample_rate,
                forced_split=forced_split,
            )

        if forced_split:
            overlap_start = max(start_sample, end_sample - self.pre_roll_samples)
            self._pre_roll = self._records_after(overlap_start)
        else:
            self._pre_roll = self._records_after(end_sample)
        self._trim_pre_roll()
        self._segment_records = []
        self._active = False
        self._silence_samples = 0
        return segment

    def process(
        self,
        chunk: np.ndarray,
        probability: float,
        chunk_started_at: float,
        *,
        valid_samples: int | None = None,
    ) -> tuple[AudioSegment, ...]:
        """Consume one model-sized chunk and return zero or one completed segment."""

        if not isinstance(chunk, np.ndarray) or chunk.dtype != np.float32:
            raise ValueError("Segmenter chunks must be float32 NumPy arrays.")
        if chunk.ndim != 1 or chunk.size != self.chunk_samples:
            raise ValueError(f"Segmenter chunks must contain {self.chunk_samples} samples.")
        if not np.isfinite(chunk).all() or not np.isfinite(probability):
            raise ValueError("Segmenter input must contain finite values.")
        if not 0.0 <= probability <= 1.0:
            raise ValueError("Speech probability must be between zero and one.")
        valid = self.chunk_samples if valid_samples is None else valid_samples
        if not 1 <= valid <= self.chunk_samples:
            raise ValueError("valid_samples must be between 1 and chunk_samples.")
        if self._stream_origin is None:
            self._stream_origin = chunk_started_at - self._next_sample / self.sample_rate

        record = _ChunkRecord(self._next_sample, chunk[:valid].copy())
        self._next_sample += valid

        if not self._active:
            if probability < self.threshold:
                self._pre_roll.append(record)
                self._trim_pre_roll()
                return ()
            self._active = True
            self._segment_records = [*self._pre_roll, record]
            self._pre_roll.clear()
            self._speech_start_sample = record.start_sample
            self._last_speech_end_sample = record.end_sample
            self._silence_samples = 0
        else:
            self._segment_records.append(record)
            if probability >= self.threshold:
                self._last_speech_end_sample = record.end_sample
                self._silence_samples = 0
            elif probability < self.negative_threshold:
                self._silence_samples += valid
            else:
                self._last_speech_end_sample = record.end_sample
                self._silence_samples = 0

        completed: AudioSegment | None = None
        if self._silence_samples >= self.min_silence_samples:
            end_sample = min(
                self._next_sample,
                self._last_speech_end_sample + self.speech_pad_samples,
            )
            completed = self._finish(end_sample, forced_split=False)
        elif self._next_sample - self._segment_records[0].start_sample >= self.max_segment_samples:
            completed = self._finish(self._next_sample, forced_split=True)
        return (completed,) if completed is not None else ()

    def flush(self) -> tuple[AudioSegment, ...]:
        """Finish the last valid active segment at end of input."""

        if not self._active:
            return ()
        end_sample = min(
            self._next_sample,
            self._last_speech_end_sample + self.speech_pad_samples,
        )
        completed = self._finish(end_sample, forced_split=False)
        return (completed,) if completed is not None else ()
