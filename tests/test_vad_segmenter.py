from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from live_subtitles.realtime.segmenter import VadSegmenter


CHUNK = np.full(512, 0.1, dtype=np.float32)


def segmenter(**overrides: object) -> VadSegmenter:
    settings: dict[str, object] = {
        "min_silence_ms": 64,
        "speech_pad_ms": 32,
        "pre_roll_ms": 64,
        "min_segment_ms": 64,
        "max_segment_seconds": 5.0,
    }
    settings.update(overrides)
    return VadSegmenter(**settings)  # type: ignore[arg-type]


def feed(vad: VadSegmenter, probabilities: list[float]) -> list[object]:
    results: list[object] = []
    for index, probability in enumerate(probabilities):
        results.extend(vad.process(CHUNK, probability, index * 0.032))
    return results


def test_silence_produces_no_segment() -> None:
    vad = segmenter()
    assert feed(vad, [0.0] * 10) == []
    assert vad.flush() == ()


def test_one_utterance_preserves_pre_roll_and_padding() -> None:
    vad = segmenter()
    results = feed(vad, [0.0, 0.0, 0.8, 0.8, 0.8, 0.0, 0.0])
    assert len(results) == 1
    result = results[0]
    assert result.start_sample == 0
    assert result.end_sample == 3072
    assert result.samples.size == 3072
    assert result.forced_split is False


def test_short_noise_is_ignored() -> None:
    vad = segmenter(min_segment_ms=64)
    assert feed(vad, [0.0, 0.8, 0.0, 0.0]) == []
    assert vad.ignored_short_segments == 1


def test_two_utterances_preserve_order() -> None:
    vad = segmenter()
    results = feed(vad, [0.0, 0.8, 0.8, 0.0, 0.0, 0.0, 0.8, 0.8, 0.0, 0.0])
    assert len(results) == 2
    assert results[0].start_sample < results[1].start_sample
    assert results[0].end_sample <= results[1].start_sample


def test_middle_hysteresis_does_not_start_silence() -> None:
    vad = segmenter()
    results = feed(vad, [0.8, 0.8, 0.4, 0.4, 0.8, 0.0, 0.0])
    assert len(results) == 1
    assert results[0].end_sample == 3072


def test_middle_hysteresis_extends_the_current_speech_boundary() -> None:
    vad = segmenter()
    results = feed(vad, [0.8, 0.8, 0.4, 0.4, 0.0, 0.0])
    assert len(results) == 1
    assert results[0].end_sample == 2560


def test_maximum_length_forces_split_and_keeps_following_audio() -> None:
    vad = segmenter(
        pre_roll_ms=32,
        min_segment_ms=32,
        max_segment_seconds=0.096,
    )
    results = feed(vad, [0.8, 0.8, 0.8, 0.8])
    results.extend(vad.flush())
    assert len(results) == 2
    assert results[0].forced_split is True
    assert results[1].forced_split is False
    assert results[0].end_sample >= results[1].start_sample


def test_flush_finishes_active_speech() -> None:
    vad = segmenter()
    assert feed(vad, [0.0, 0.8, 0.8]) == []
    flushed = vad.flush()
    assert len(flushed) == 1
    assert flushed[0].end_sample == 1536


def test_reset_removes_old_stream_state() -> None:
    vad = segmenter()
    feed(vad, [0.8, 0.8])
    vad.reset()
    assert vad.flush() == ()
    assert vad.ignored_short_segments == 0


def test_audio_segment_samples_are_read_only() -> None:
    vad = segmenter()
    result = feed(vad, [0.8, 0.8, 0.0, 0.0])[0]
    with pytest.raises(ValueError):
        result.samples[0] = 1.0


def test_segmenter_source_has_no_external_runtime_dependency() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "live_subtitles"
        / "realtime"
        / "segmenter.py"
    ).read_text(encoding="utf-8")
    assert "sounddevice" not in source
    assert "torch" not in source
    assert "silero_vad" not in source
