from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from live_subtitles.realtime.file_vad import VadFileError, percentile, run_vad_file


class FakeVad:
    def __init__(self, probabilities: list[float], model_path: Path) -> None:
        self.probabilities = iter(probabilities)
        self.model_path = model_path
        self.load_seconds = 0.25
        self.prepare_calls = 0
        self.reset_calls = 0

    def prepare(self) -> None:
        self.prepare_calls += 1

    def reset(self) -> None:
        self.reset_calls += 1

    def speech_probability(self, chunk: np.ndarray) -> float:
        assert chunk.shape == (512,)
        assert chunk.dtype == np.float32
        return next(self.probabilities)


def write_wav(
    path: Path,
    samples: np.ndarray,
    *,
    channels: int = 1,
    sample_rate: int = 16_000,
) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.astype("<i2").tobytes())


def test_vad_file_defaults_to_no_output_and_reports_segments(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    probabilities = [0.0, 0.0, *([0.8] * 10), 0.0, 0.0]
    write_wav(source, np.arange(512 * len(probabilities), dtype=np.int16))
    model = FakeVad(probabilities, tmp_path / "model.onnx")
    times = iter(float(value) for value in range(len(probabilities) * 2))
    result = run_vad_file(
        source,
        model=model,  # type: ignore[arg-type]
        min_silence_ms=64,
        clock=lambda: next(times),
    )
    assert model.prepare_calls == 1
    assert model.reset_calls == 1
    assert result.total_chunks == len(probabilities)
    assert len(result.segments) == 1
    assert result.output_paths == ()
    assert result.average_chunk_seconds == 1.0
    assert result.p95_chunk_seconds == 1.0
    assert list(tmp_path.glob("segment-*.wav")) == []


def test_vad_file_can_write_strict_pcm16_segments(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    probabilities = [*([0.8] * 10), 0.0, 0.0]
    write_wav(source, np.full(512 * len(probabilities), 1000, dtype=np.int16))
    model = FakeVad(probabilities, tmp_path / "model.onnx")
    result = run_vad_file(
        source,
        model=model,  # type: ignore[arg-type]
        min_silence_ms=64,
        output_dir=tmp_path / "segments",
    )
    assert len(result.output_paths) == 1
    with wave.open(str(result.output_paths[0]), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16_000


@pytest.mark.parametrize(
    ("channels", "sample_rate", "message"),
    [(2, 16_000, "mono"), (1, 48_000, "16000 Hz")],
)
def test_vad_file_rejects_unsupported_wav_before_model_prepare(
    channels: int,
    sample_rate: int,
    message: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    write_wav(source, np.zeros(1024 * channels, dtype=np.int16), channels=channels, sample_rate=sample_rate)
    model = FakeVad([], tmp_path / "model.onnx")
    with pytest.raises(VadFileError, match=message):
        run_vad_file(source, model=model)  # type: ignore[arg-type]
    assert model.prepare_calls == 0


def test_partial_final_chunk_is_zero_padded(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    write_wav(source, np.full(700, 500, dtype=np.int16))
    model = FakeVad([0.0, 0.0], tmp_path / "model.onnx")
    result = run_vad_file(source, model=model)  # type: ignore[arg-type]
    assert result.total_chunks == 2
    assert result.frame_count == 700


def test_percentile_uses_linear_interpolation() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 95) == pytest.approx(3.85)
