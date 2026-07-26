from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from live_subtitles.audio.recording import RecordingError, list_input_devices, record_wav


class FakeSoundDevice:
    def __init__(self) -> None:
        self.default = SimpleNamespace(device=(1, -1))
        self.rec_calls: list[dict[str, object]] = []
        self.wait_calls = 0

    @staticmethod
    def query_devices() -> list[dict[str, object]]:
        return [
            {"name": "Output only", "max_input_channels": 0, "default_samplerate": 48_000.0},
            {"name": "麦克风 / Микрофон", "max_input_channels": 2, "default_samplerate": 48_000.0},
        ]

    def rec(self, frames: int, **kwargs: object) -> np.ndarray:
        self.rec_calls.append({"frames": frames, **kwargs})
        return np.array([[-2.0], [-0.5], [0.0], [0.5], [2.0]], dtype=np.float32)

    def wait(self) -> None:
        self.wait_calls += 1


@pytest.mark.parametrize("seconds", [0, -1, -0.1])
def test_record_rejects_non_positive_seconds(seconds: float, tmp_path: Path) -> None:
    with pytest.raises(RecordingError, match="greater than 0"):
        record_wav(tmp_path / "bad.wav", seconds=seconds, sd=FakeSoundDevice())


def test_record_rejects_more_than_thirty_seconds(tmp_path: Path) -> None:
    with pytest.raises(RecordingError, match="must not exceed 30"):
        record_wav(tmp_path / "bad.wav", seconds=30.01, sd=FakeSoundDevice())


def test_device_list_filters_output_devices_and_marks_default() -> None:
    devices = list_input_devices(FakeSoundDevice())
    assert len(devices) == 1
    assert devices[0].index == 1
    assert devices[0].is_default
    assert devices[0].name == "麦克风 / Микрофон"


def test_record_writes_pcm16_mono_wav(tmp_path: Path) -> None:
    fake = FakeSoundDevice()
    output = tmp_path / "nested" / "sample.wav"
    result = record_wav(output, seconds=0.5, sample_rate=16_000, sd=fake)

    assert result.path == output.resolve()
    assert result.frames == 5
    assert result.size_bytes == 44 + (5 * 2)
    assert fake.wait_calls == 1
    assert fake.rec_calls[0]["dtype"] == "float32"
    assert fake.rec_calls[0]["channels"] == 1
    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16_000
        assert wav_file.getnframes() == 5
