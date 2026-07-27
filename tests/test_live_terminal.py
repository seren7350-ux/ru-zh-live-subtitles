from __future__ import annotations

import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from live_subtitles.realtime import segment_processor as segment_processor_module
from live_subtitles.pipeline.offline_file import (
    PipelineAsrError,
    PipelinePrepareMetrics,
    PipelineTranslationError,
)
from live_subtitles.realtime.live_subtitles import LiveTerminalSession
from live_subtitles.realtime.segment_processor import (
    BACKLOG_MESSAGE,
    LiveSubtitleResult,
    SegmentBacklogError,
    SegmentProcessor,
    SegmentProcessorError,
)
from live_subtitles.realtime.segmenter import AudioSegment


def segment(index: int = 0, *, seconds: float = 1.0) -> AudioSegment:
    now = time.perf_counter()
    samples = np.linspace(-0.25, 0.25, round(16_000 * seconds), dtype=np.float32)
    return AudioSegment(
        samples=samples,
        start_sample=index * samples.size,
        end_sample=(index + 1) * samples.size,
        started_at=now - seconds - 0.2,
        ended_at=now - 0.2,
        forced_split=False,
    )


class FakePipeline:
    def __init__(self, *, fail_first_asr: bool = False) -> None:
        self.fail_first_asr = fail_first_asr
        self.transcribe_calls = 0
        self.translate_calls = 0
        self.paths: list[Path] = []
        self.russian_inputs: list[str] = []
        self.active = 0
        self.maximum_active = 0
        self._lock = threading.Lock()

    def transcribe_file(self, path: Path) -> tuple[str, Any]:
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        self.transcribe_calls += 1
        self.paths.append(path)
        assert path.exists()
        with wave.open(str(path), "rb") as wav_file:
            assert wav_file.getnchannels() == 1
            assert wav_file.getsampwidth() == 2
            assert wav_file.getframerate() == 16_000
        if self.fail_first_asr and self.transcribe_calls == 1:
            with self._lock:
                self.active -= 1
            raise PipelineAsrError("synthetic empty transcription")
        return (
            f"Russian {self.transcribe_calls}",
            SimpleNamespace(recognition_seconds=0.01),
        )

    def translate_text(self, text: str) -> tuple[str, Any]:
        self.translate_calls += 1
        self.russian_inputs.append(text)
        with self._lock:
            self.active -= 1
        return f"Chinese {self.translate_calls}", SimpleNamespace(translation_seconds=0.02)


def test_processor_preserves_order_is_serial_and_removes_all_temp_wavs() -> None:
    pipeline = FakePipeline()
    processor = SegmentProcessor(pipeline, queue_size=4)
    processor.start()
    for index in range(3):
        processor.enqueue(index + 1, segment(index))
    processor.finish()

    assert [result.index for result in processor.results] == [1, 2, 3]
    assert [result.russian_text for result in processor.results] == [
        "Russian 1",
        "Russian 2",
        "Russian 3",
    ]
    assert pipeline.maximum_active == 1
    assert all(not path.exists() for path in pipeline.paths)
    metrics = processor.metrics()
    assert metrics.enqueued_segments == metrics.dequeued_segments == 3
    assert metrics.successful_segments == 3
    assert metrics.failed_segments == 0
    assert metrics.queue_final_depth == 0
    assert metrics.temp_files_created == metrics.temp_files_deleted == 3
    assert metrics.temp_files_remaining == 0
    assert metrics.worker_exited


def test_segment_asr_error_is_reported_and_next_segment_continues() -> None:
    pipeline = FakePipeline(fail_first_asr=True)
    processor = SegmentProcessor(pipeline, queue_size=2)
    processor.start()
    processor.enqueue(1, segment(0))
    processor.enqueue(2, segment(1))
    processor.finish()

    assert len(processor.results) == 2
    assert not processor.results[0].succeeded
    assert processor.results[0].error_stage == "asr"
    assert processor.results[1].succeeded
    assert pipeline.translate_calls == 1
    assert all(not path.exists() for path in pipeline.paths)
    assert processor.fatal_error is None


def test_translation_error_deletes_temp_and_next_segment_continues() -> None:
    class TranslationFailurePipeline(FakePipeline):
        def translate_text(self, text: str) -> tuple[str, Any]:
            if self.translate_calls == 0:
                self.translate_calls += 1
                self.russian_inputs.append(text)
                with self._lock:
                    self.active -= 1
                raise PipelineTranslationError("synthetic generation failure")
            return super().translate_text(text)

    pipeline = TranslationFailurePipeline()
    processor = SegmentProcessor(pipeline, queue_size=2)
    processor.start()
    processor.enqueue(1, segment(0))
    processor.enqueue(2, segment(1))
    processor.finish()

    assert processor.results[0].error_stage == "translation"
    assert processor.results[0].russian_text == "Russian 1"
    assert processor.results[1].succeeded
    assert pipeline.russian_inputs == ["Russian 1", "Russian 2"]
    assert all(not path.exists() for path in pipeline.paths)
    assert processor.metrics().temp_files_remaining == 0


def test_latency_timestamps_and_metrics_use_one_monotonic_clock() -> None:
    processor = SegmentProcessor(FakePipeline(), queue_size=1)
    processor.start()
    processor.enqueue(1, segment())
    processor.finish()
    result = processor.results[0]

    assert result.segment_end_at <= result.emitted_at <= result.queued_at
    assert result.queued_at <= result.processing_started_at
    assert result.processing_started_at <= result.russian_ready_at <= result.chinese_ready_at  # type: ignore[operator]
    assert result.vad_release_latency_seconds == pytest.approx(
        result.emitted_at - result.segment_end_at
    )
    assert result.russian_latency_seconds == pytest.approx(
        result.russian_ready_at - result.segment_end_at  # type: ignore[operator]
    )
    assert result.chinese_latency_seconds == pytest.approx(
        result.chinese_ready_at - result.segment_end_at  # type: ignore[operator]
    )
    assert result.rtf == pytest.approx(
        result.processing_seconds / result.audio_duration_seconds
    )


def test_segment_queue_overflow_is_fatal_and_never_silently_drops() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingPipeline(FakePipeline):
        def transcribe_file(self, path: Path) -> tuple[str, Any]:
            entered.set()
            assert release.wait(2.0)
            return super().transcribe_file(path)

    processor = SegmentProcessor(BlockingPipeline(), queue_size=1)
    processor.start()
    processor.enqueue(1, segment(0))
    assert entered.wait(1.0)
    processor.enqueue(2, segment(1))
    with pytest.raises(SegmentBacklogError, match=BACKLOG_MESSAGE):
        processor.enqueue(3, segment(2))
    assert processor.fatal_event.is_set()
    assert processor.fatal_error == BACKLOG_MESSAGE
    release.set()
    processor.finish()
    metrics = processor.metrics()
    assert metrics.backlog_failures == 1
    assert metrics.enqueued_segments == metrics.dequeued_segments == 2


@pytest.mark.parametrize("queue_size", [0, 33])
def test_segment_queue_bounds(queue_size: int) -> None:
    with pytest.raises(SegmentProcessorError, match="between 1 and 32"):
        SegmentProcessor(FakePipeline(), queue_size=queue_size)


def test_join_timeout_is_fatal_but_finite_and_temp_is_eventually_cleaned() -> None:
    entered = threading.Event()
    release = threading.Event()

    class StuckPipeline(FakePipeline):
        def transcribe_file(self, path: Path) -> tuple[str, Any]:
            self.paths.append(path)
            entered.set()
            assert release.wait(2.0)
            return "Russian", SimpleNamespace(recognition_seconds=0.01)

        def translate_text(self, text: str) -> tuple[str, Any]:
            return "Chinese", SimpleNamespace(translation_seconds=0.01)

    pipeline = StuckPipeline()
    processor = SegmentProcessor(pipeline, queue_size=1, join_timeout=0.01)
    processor.start()
    processor.enqueue(1, segment())
    assert entered.wait(1.0)
    started = time.perf_counter()
    processor.finish()
    assert time.perf_counter() - started < 0.5
    assert "did not exit" in (processor.fatal_error or "")
    assert processor.fatal_event.is_set()
    release.set()
    assert processor._worker_exited.wait(1.0)
    assert all(not path.exists() for path in pipeline.paths)


def test_temp_wav_write_failure_is_fatal_and_deletes_created_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_paths: list[Path] = []

    def fail_write(path: Path, *_args: Any, **_kwargs: Any) -> None:
        created_paths.append(path)
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(segment_processor_module, "write_pcm16_mono_wav", fail_write)
    processor = SegmentProcessor(FakePipeline(), queue_size=1)
    processor.start()
    processor.enqueue(1, segment())
    assert processor._worker_exited.wait(1.0)
    processor.finish()

    assert "temporary PCM16 WAV" in (processor.fatal_error or "")
    assert processor.fatal_event.is_set()
    assert len(created_paths) == 1
    assert not created_paths[0].exists()
    metrics = processor.metrics()
    assert metrics.temp_files_created == metrics.temp_files_deleted == 1
    assert metrics.temp_files_remaining == 0


def test_result_and_latency_windows_are_bounded_to_8192() -> None:
    processor = SegmentProcessor(FakePipeline())
    for index in range(8_200):
        processor._record_result(
            LiveSubtitleResult(
                index=index,
                segment_start_at=0.0,
                segment_end_at=1.0,
                emitted_at=1.1,
                queued_at=1.1,
                processing_started_at=1.2,
                russian_ready_at=1.3,
                chinese_ready_at=1.4,
                audio_duration_seconds=1.0,
                queue_wait_seconds=0.1,
                asr_seconds=0.1,
                translation_seconds=0.1,
                processing_seconds=0.2,
                rtf=0.2,
                vad_release_latency_seconds=0.1,
                russian_latency_seconds=0.3,
                chinese_latency_seconds=0.4,
                russian_text="ru",
                chinese_text="zh",
                succeeded=True,
                error_stage=None,
                error=None,
            )
        )
    metrics = processor.metrics()
    assert metrics.successful_segments == 8_200
    assert metrics.retained_results == 8_192
    assert processor.results[0].index == 8
    assert processor._queue_waits.retained_count == 8_192


class FakeVad:
    provider = "CPUExecutionProvider"
    load_seconds = 0.01
    session_creation_count = 0

    def __init__(self, tmp_path: Path) -> None:
        self.model_path = tmp_path / "silero.onnx"

    def prepare(self) -> None:
        self.session_creation_count = 1

    @staticmethod
    def reset() -> None:
        return None

    @staticmethod
    def speech_probability(_samples: np.ndarray) -> float:
        return 0.0


class FakeStream:
    def __init__(self) -> None:
        self.stopped = False
        self.closed = False

    @staticmethod
    def start() -> None:
        return None

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FakeSoundDevice:
    default = SimpleNamespace(device=(0, -1))

    def __init__(self) -> None:
        self.stream = FakeStream()

    @staticmethod
    def query_devices() -> list[dict[str, object]]:
        return [
            {
                "name": "Fake microphone",
                "max_input_channels": 1,
                "default_samplerate": 16_000,
            }
        ]

    @staticmethod
    def check_input_settings(**_kwargs: Any) -> None:
        return None

    def InputStream(self, **_kwargs: Any) -> FakeStream:  # noqa: N802
        return self.stream


class PreparedFakePipeline(FakePipeline):
    def __init__(self, order: list[str] | None = None) -> None:
        super().__init__()
        self.prepare_calls = 0
        self.order = order

    def prepare(self) -> PipelinePrepareMetrics:
        self.prepare_calls += 1
        if self.order is not None:
            self.order.append("models")
        return PipelinePrepareMetrics(0.1, 0.2, 0.3)


def test_live_terminal_ctrl_c_releases_microphone_and_both_workers(tmp_path: Path) -> None:
    sounddevice = FakeSoundDevice()
    pipeline = PreparedFakePipeline()

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    session = LiveTerminalSession(
        duration=0,
        pipeline=pipeline,  # type: ignore[arg-type]
        vad=FakeVad(tmp_path),
        sounddevice_module=sounddevice,
        sleeper=interrupt,
        join_timeout=1.0,
    )
    result = session.run()

    assert result.succeeded
    assert result.vad.stop_reason == "Ctrl+C"
    assert result.vad.metrics.worker_exited
    assert result.subtitle_metrics.worker_exited
    assert result.vad.metrics.microphone_closed
    assert sounddevice.stream.stopped and sounddevice.stream.closed
    assert pipeline.prepare_calls == 1


def test_live_terminal_duration_releases_microphone_and_workers(tmp_path: Path) -> None:
    sounddevice = FakeSoundDevice()
    result = LiveTerminalSession(
        duration=0.001,
        pipeline=PreparedFakePipeline(),  # type: ignore[arg-type]
        vad=FakeVad(tmp_path),
        sounddevice_module=sounddevice,
        join_timeout=1.0,
    ).run()
    assert result.succeeded
    assert result.vad.stop_reason == "duration elapsed"
    assert result.vad.metrics.microphone_closed
    assert result.vad.metrics.worker_exited
    assert result.subtitle_metrics.worker_exited


def test_live_terminal_public_stop_is_idempotent_and_prevents_microphone_open(
    tmp_path: Path,
) -> None:
    sounddevice = FakeSoundDevice()
    input_stream_calls = 0
    original_input_stream = sounddevice.InputStream

    def count_input_stream(**kwargs: Any) -> FakeStream:
        nonlocal input_stream_calls
        input_stream_calls += 1
        return original_input_stream(**kwargs)

    sounddevice.InputStream = count_input_stream  # type: ignore[method-assign]
    session = LiveTerminalSession(
        duration=0,
        pipeline=PreparedFakePipeline(),  # type: ignore[arg-type]
        vad=FakeVad(tmp_path),
        sounddevice_module=sounddevice,
        join_timeout=1.0,
    )
    session.request_stop("window closed")
    session.request_stop("duplicate")
    result = session.run()
    assert result.succeeded
    assert result.vad.stop_reason == "window closed"
    assert input_stream_calls == 0
    assert result.vad.metrics.microphone_closed
    assert result.vad.metrics.worker_exited
    assert result.subtitle_metrics.worker_exited


def test_prepare_order_finishes_before_microphone_start(tmp_path: Path) -> None:
    order: list[str] = []

    class OrderedVad(FakeVad):
        def validate_cache(self) -> Path:
            order.append("vad cache")
            return self.model_path

        def prepare(self) -> None:
            order.append("vad session")
            super().prepare()

    class OrderedSoundDevice(FakeSoundDevice):
        @staticmethod
        def check_input_settings(**_kwargs: Any) -> None:
            order.append("microphone check")

        def InputStream(self, **_kwargs: Any) -> FakeStream:  # noqa: N802
            order.append("microphone open")
            return super().InputStream(**_kwargs)

    session = LiveTerminalSession(
        duration=0.001,
        pipeline=PreparedFakePipeline(order),  # type: ignore[arg-type]
        vad=OrderedVad(tmp_path),
        sounddevice_module=OrderedSoundDevice(),
        join_timeout=1.0,
    )
    session.prepare()
    assert order == ["vad cache", "microphone check", "vad session", "models"]
    session.run()
    assert order[-1] == "microphone open"


def test_live_terminal_source_has_no_user_path_token_network_or_parallel_asr() -> None:
    source_root = Path(__file__).parents[1] / "src" / "live_subtitles" / "realtime"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))
    lowered = source.lower()
    assert "c:\\users\\seren" not in lowered
    assert "huggingface token" not in lowered
    assert "requests." not in lowered
    assert source.count('name="live-subtitle-worker"') == 1
