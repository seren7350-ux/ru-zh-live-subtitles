"""Immutable messages exchanged between background workers and the Tk thread."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreparingEvent:
    message: str
    created_at: float


@dataclass(frozen=True)
class ModelsReadyEvent:
    vad_prepare_seconds: float
    asr_prepare_seconds: float
    translation_prepare_seconds: float
    total_prepare_seconds: float
    translation_device: str
    created_at: float


@dataclass(frozen=True)
class ListeningEvent:
    device_name: str
    created_at: float


@dataclass(frozen=True)
class SubtitleEvent:
    index: int
    russian_text: str
    chinese_text: str
    audio_duration_seconds: float
    russian_latency_seconds: float | None
    chinese_latency_seconds: float | None
    created_at: float


@dataclass(frozen=True)
class SegmentErrorEvent:
    index: int
    stage: str
    message: str
    created_at: float


@dataclass(frozen=True)
class SessionMetricsSnapshot:
    captured_blocks: int
    processed_blocks: int
    detected_segments: int
    successful_subtitles: int
    failed_subtitles: int
    dropped_blocks: int
    sequence_gaps: int
    audio_queue_high_watermark: int
    audio_queue_capacity: int
    segment_queue_high_watermark: int
    segment_queue_capacity: int
    microphone_closed: bool
    vad_worker_exited: bool
    subtitle_worker_exited: bool


@dataclass(frozen=True)
class SessionFinishedEvent:
    succeeded: bool
    stop_reason: str
    successful_subtitles: int
    failed_subtitles: int
    metrics: SessionMetricsSnapshot
    created_at: float


@dataclass(frozen=True)
class FatalErrorEvent:
    message: str
    created_at: float


@dataclass(frozen=True)
class StoppedEvent:
    reason: str
    created_at: float


GuiEvent = (
    PreparingEvent
    | ModelsReadyEvent
    | ListeningEvent
    | SubtitleEvent
    | SegmentErrorEvent
    | SessionFinishedEvent
    | FatalErrorEvent
    | StoppedEvent
)
