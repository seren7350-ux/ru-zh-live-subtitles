from __future__ import annotations

import queue
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from live_subtitles.realtime import live_vad
from live_subtitles.realtime.live_vad import LiveVadError, LiveVadSession
from live_subtitles.realtime.metrics import (
    AudioBlock,
    TimingAccumulator,
    percentile,
    summarize_timings,
)
from live_subtitles.realtime.segmenter import AudioSegment


class FakeVad:
    def __init__(self, tmp_path: Path, probabilities: list[float] | None = None) -> None:
        self.model_path = tmp_path / "silero_vad.onnx"
        self.provider = "CPUExecutionProvider"
        self.load_seconds = 0.012
        self.session_creation_count = 0
        self.prepare_calls = 0
        self.reset_calls = 0
        self.probabilities = list(probabilities or [])
        self.raise_inference = False
        self.received_sizes: list[int] = []

    def prepare(self) -> None:
        self.prepare_calls += 1
        if self.session_creation_count == 0:
            self.session_creation_count = 1

    def reset(self) -> None:
        self.reset_calls += 1

    def speech_probability(self, _samples: np.ndarray) -> float:
        self.received_sizes.append(_samples.size)
        if self.raise_inference:
            raise RuntimeError("synthetic inference failure")
        return self.probabilities.pop(0) if self.probabilities else 0.0


class CallbackStream:
    def __init__(self, kwargs: dict[str, Any], blocks: int) -> None:
        self.kwargs = kwargs
        self.blocks = blocks
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        callback = self.kwargs["callback"]
        for _ in range(self.blocks):
            callback(np.zeros((512, 1), dtype=np.float32), 512, None, None)

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FakeSoundDevice:
    def __init__(self, blocks: int = 4) -> None:
        self.default = SimpleNamespace(device=(0, -1))
        self.blocks = blocks
        self.settings: dict[str, Any] | None = None
        self.stream_kwargs: dict[str, Any] | None = None
        self.stream: CallbackStream | None = None

    @staticmethod
    def query_devices() -> list[dict[str, object]]:
        return [
            {
                "name": "Test microphone",
                "max_input_channels": 1,
                "default_samplerate": 16_000.0,
            }
        ]

    def check_input_settings(self, **kwargs: Any) -> None:
        self.settings = kwargs

    def InputStream(self, **kwargs: Any) -> CallbackStream:  # noqa: N802
        self.stream_kwargs = kwargs
        self.stream = CallbackStream(kwargs, self.blocks)
        return self.stream


def block(sequence: int) -> AudioBlock:
    timestamp = sequence * 0.032
    return AudioBlock(
        sequence,
        np.zeros(512, dtype=np.float32),
        timestamp,
        timestamp,
    )


def run_worker(session: LiveVadSession, blocks: list[AudioBlock]) -> None:
    for value in blocks:
        session._audio_queue.put_nowait(value)
    session._request_worker_stop()
    session._worker()


@pytest.mark.parametrize("duration", [-1.0, 3_601.0])
def test_duration_bounds_are_enforced(duration: float) -> None:
    with pytest.raises(LiveVadError, match="Duration"):
        LiveVadSession(duration=duration)


@pytest.mark.parametrize("queue_size", [15, 2_001])
def test_queue_bounds_are_enforced(queue_size: int) -> None:
    with pytest.raises(LiveVadError, match="Queue size"):
        LiveVadSession(queue_size=queue_size)


def test_default_queue_is_bounded_to_320_blocks() -> None:
    session = LiveVadSession()
    assert session.queue_size == 320
    assert session._audio_queue.maxsize == 320


def test_prepare_checks_device_and_creates_only_one_cached_session(tmp_path: Path) -> None:
    vad = FakeVad(tmp_path)
    sd = FakeSoundDevice()
    session = LiveVadSession(vad=vad, sounddevice_module=sd)
    first = session.prepare()
    second = session.prepare()
    assert first is second
    assert vad.prepare_calls == 1
    assert vad.session_creation_count == 1
    assert sd.settings == {
        "device": 0,
        "channels": 1,
        "dtype": "float32",
        "samplerate": 16_000,
    }


def test_worker_processes_blocks_in_order_and_resets_both_ends(tmp_path: Path) -> None:
    vad = FakeVad(tmp_path, [0.0, 0.0, 0.0])
    session = LiveVadSession(vad=vad)
    run_worker(session, [block(0), block(1), block(2)])
    assert session._processed_blocks == 3
    assert session._sequence_gaps == 0
    assert session._worker_error is None
    assert vad.reset_calls == 2
    assert vad.received_sizes == [512, 512, 512]
    assert session._worker_exited.is_set()


def test_worker_rejects_sequence_gap_as_infrastructure_error(tmp_path: Path) -> None:
    vad = FakeVad(tmp_path)
    session = LiveVadSession(vad=vad)
    run_worker(session, [block(0), block(2)])
    assert session._sequence_gaps == 1
    assert "expected 1, got 2" in (session._worker_error or "")
    assert session._fatal_event.is_set()


def test_worker_propagates_vad_exception(tmp_path: Path) -> None:
    vad = FakeVad(tmp_path)
    vad.raise_inference = True
    session = LiveVadSession(vad=vad)
    run_worker(session, [block(0)])
    assert "synthetic inference failure" in (session._worker_error or "")
    assert session._fatal_event.is_set()


def test_worker_flushes_segment_and_emits_callback(tmp_path: Path) -> None:
    probabilities = [0.9] * 12
    vad = FakeVad(tmp_path, probabilities)
    emitted: list[tuple[int, AudioSegment]] = []
    session = LiveVadSession(
        vad=vad,
        on_segment=lambda index, segment: emitted.append((index, segment)),
    )
    run_worker(session, [block(index) for index in range(12)])
    assert len(session._segments) == 1
    assert len(emitted) == 1
    assert emitted[0][0] == 1


def test_worker_passes_vad_probability_to_segmenter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: list[tuple[float, int]] = []

    class FakeSegmenter:
        ignored_short_segments = 0

        def __init__(self, **_kwargs: object) -> None:
            pass

        def process(
            self,
            samples: np.ndarray,
            probability: float,
            _started_at: float,
        ) -> tuple[()]:
            observed.append((probability, samples.size))
            return ()

        @staticmethod
        def flush() -> tuple[()]:
            return ()

    monkeypatch.setattr(live_vad, "VadSegmenter", FakeSegmenter)
    vad = FakeVad(tmp_path, [0.625])
    session = LiveVadSession(vad=vad)
    run_worker(session, [block(0)])
    assert observed == [(0.625, 512)]


def test_show_probabilities_is_opt_in(tmp_path: Path) -> None:
    observed: list[tuple[int, float]] = []
    vad = FakeVad(tmp_path, [0.25])
    disabled = LiveVadSession(
        vad=vad,
        on_probability=lambda sequence, probability: observed.append((sequence, probability)),
    )
    run_worker(disabled, [block(0)])
    assert observed == []

    vad2 = FakeVad(tmp_path, [0.75])
    enabled = LiveVadSession(
        vad=vad2,
        show_probabilities=True,
        on_probability=lambda sequence, probability: observed.append((sequence, probability)),
    )
    run_worker(enabled, [block(0)])
    assert observed == [(0, 0.75)]


def test_run_uses_exact_stream_format_and_reports_clean_shutdown(tmp_path: Path) -> None:
    vad = FakeVad(tmp_path)
    sd = FakeSoundDevice(blocks=4)
    session = LiveVadSession(
        duration=0.001,
        queue_size=16,
        vad=vad,
        sounddevice_module=sd,
    )
    result = session.run()
    assert result.succeeded
    assert result.metrics.captured_blocks == 4
    assert result.metrics.processed_blocks == 4
    assert result.metrics.dropped_blocks == 0
    assert result.metrics.sequence_gaps == 0
    assert result.metrics.worker_exited
    assert result.metrics.microphone_closed
    assert result.metrics.session_creation_count == 1
    assert sd.stream_kwargs is not None
    assert sd.stream_kwargs["blocksize"] == 512
    assert sd.stream_kwargs["samplerate"] == 16_000
    assert sd.stream_kwargs["channels"] == 1
    assert sd.stream_kwargs["dtype"] == "float32"
    assert sd.stream is not None and sd.stream.stopped and sd.stream.closed


def test_ctrl_c_still_joins_worker_and_releases_microphone(tmp_path: Path) -> None:
    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    vad = FakeVad(tmp_path)
    sd = FakeSoundDevice(blocks=1)
    result = LiveVadSession(
        duration=0,
        queue_size=16,
        vad=vad,
        sounddevice_module=sd,
        sleeper=interrupt,
    ).run()
    assert result.stop_reason == "Ctrl+C"
    assert result.metrics.worker_exited
    assert result.metrics.microphone_closed


def test_runtime_inference_failure_is_returned_after_cleanup(tmp_path: Path) -> None:
    vad = FakeVad(tmp_path)
    vad.raise_inference = True
    sd = FakeSoundDevice(blocks=1)
    result = LiveVadSession(
        duration=0.1,
        queue_size=16,
        vad=vad,
        sounddevice_module=sd,
    ).run()
    assert not result.succeeded
    assert "VAD worker failed" in result.errors[0]
    assert result.metrics.worker_exited
    assert result.metrics.microphone_closed


def test_join_timeout_returns_error_and_names_live_worker(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingVad(FakeVad):
        def speech_probability(self, samples: np.ndarray) -> float:
            self.received_sizes.append(samples.size)
            entered.set()
            release.wait(1.0)
            return 0.0

    vad = BlockingVad(tmp_path)
    session = LiveVadSession(
        duration=0.001,
        queue_size=16,
        vad=vad,
        sounddevice_module=FakeSoundDevice(blocks=1),
        join_timeout=0.01,
    )
    try:
        result = session.run()
        assert entered.is_set()
        assert not result.succeeded
        assert "VAD worker did not exit" in result.errors[0]
        assert not result.metrics.worker_exited
        assert result.metrics.microphone_closed
    finally:
        release.set()
        assert session._worker_exited.wait(1.0)


def test_default_run_writes_no_audio(tmp_path: Path) -> None:
    vad = FakeVad(tmp_path)
    result = LiveVadSession(
        duration=0.001,
        queue_size=16,
        vad=vad,
        sounddevice_module=FakeSoundDevice(blocks=0),
    ).run()
    assert result.output_directory is None
    assert result.output_paths == ()
    assert list(tmp_path.iterdir()) == []


def test_output_uses_unique_session_directory_and_strict_pcm16(tmp_path: Path) -> None:
    vad = FakeVad(tmp_path)
    session = LiveVadSession(vad=vad, output_dir=tmp_path / "segments")
    samples = np.linspace(-1.0, 1.0, 1_024, dtype=np.float32)
    session._segments = [AudioSegment(samples, 0, 1_024, 0.0, 0.064, False)]
    directory, paths, errors = session._save_segments()
    assert errors == []
    assert directory is not None and directory.parent == (tmp_path / "segments").resolve()
    assert len(paths) == 1
    assert paths[0].name == "segment-0001.wav"
    with wave.open(str(paths[0]), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16_000
        assert wav_file.getnframes() == 1_024
    assert not list(directory.glob("*.tmp"))


def test_output_creates_unique_empty_session_directory(tmp_path: Path) -> None:
    session = LiveVadSession(vad=FakeVad(tmp_path), output_dir=tmp_path / "segments")
    first, first_paths, first_errors = session._save_segments()
    second, second_paths, second_errors = session._save_segments()
    assert first is not None and second is not None and first != second
    assert first.is_dir() and second.is_dir()
    assert first_paths == second_paths == ()
    assert first_errors == second_errors == []


def test_save_failure_is_counted_without_leaving_partial_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = LiveVadSession(vad=FakeVad(tmp_path), output_dir=tmp_path / "segments")
    session._segments = [
        AudioSegment(np.zeros(512, dtype=np.float32), 0, 512, 0.0, 0.032, False)
    ]
    monkeypatch.setattr(live_vad, "_write_pcm16_atomic", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))
    directory, paths, errors = session._save_segments()
    assert directory is not None
    assert paths == ()
    assert errors and "disk full" in errors[0]
    assert list(directory.iterdir()) == []


def test_timing_helpers_cover_empty_median_p95_and_maximum() -> None:
    assert summarize_timings([]) == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0
    total, average, median, p95, maximum = summarize_timings([0.001, 0.003])
    assert total == pytest.approx(0.004)
    assert average == pytest.approx(0.002)
    assert median == pytest.approx(0.002)
    assert p95 == pytest.approx(0.0029)
    assert maximum == 0.003


def test_timing_accumulator_bounds_percentile_memory_but_keeps_exact_totals() -> None:
    timings = TimingAccumulator(max_samples=3)
    for value in (1.0, 2.0, 3.0, 4.0):
        timings.add(value)
    total, average, median, p95, maximum = timings.summary()
    assert timings.count == 4
    assert timings.retained_count == 3
    assert total == 10.0
    assert average == 2.5
    assert median == 3.0
    assert p95 == pytest.approx(3.9)
    assert maximum == 4.0


def test_live_modules_do_not_depend_on_asr_translation_or_user_path() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path(live_vad.__file__),
            Path(live_vad.__file__).with_name("microphone.py"),
            Path(live_vad.__file__).with_name("metrics.py"),
        )
    ).lower()
    assert "c:\\users\\seren" not in sources
    assert "onnx_asr" not in sources
    assert "transformers" not in sources
    assert "torchaudio" not in sources
    assert "silero_vad" not in sources
    assert "soundfile" not in sources


def test_cli_parser_exposes_all_live_segmentation_controls() -> None:
    from live_subtitles.cli import build_parser

    args = build_parser().parse_args(
        [
            "live-vad",
            "--device",
            "9",
            "--duration",
            "12",
            "--threshold",
            "0.6",
            "--negative-threshold",
            "0.2",
            "--min-silence-ms",
            "700",
            "--speech-pad-ms",
            "110",
            "--pre-roll-ms",
            "260",
            "--min-segment-ms",
            "310",
            "--max-segment-seconds",
            "14",
            "--audio-queue-size",
            "400",
            "--output-dir",
            "data/segments",
            "--show-probabilities",
        ]
    )
    assert args.device == 9
    assert args.duration == 12
    assert args.threshold == 0.6
    assert args.negative_threshold == 0.2
    assert args.min_silence_ms == 700
    assert args.speech_pad_ms == 110
    assert args.pre_roll_ms == 260
    assert args.min_segment_ms == 310
    assert args.max_segment_seconds == 14
    assert args.audio_queue_size == 400
    assert args.output_dir == "data/segments"
    assert args.show_probabilities
