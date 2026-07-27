from __future__ import annotations

import queue
import threading
import inspect
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from live_subtitles.audio.recording import AudioDeviceError
from live_subtitles.realtime.metrics import AudioBlock
from live_subtitles.realtime.microphone import (
    BLOCK_SECONDS,
    MicrophoneCapture,
    MicrophoneCaptureError,
    validate_live_input_device,
)


class FakeStatus:
    def __init__(self, text: str, *, input_overflow: bool = False) -> None:
        self.text = text
        self.input_overflow = input_overflow

    def __bool__(self) -> bool:
        return True

    def __str__(self) -> str:
        return self.text


class FakeStream:
    def __init__(self, *, fail_start: bool = False, fail_cleanup: bool = False) -> None:
        self.fail_start = fail_start
        self.fail_cleanup = fail_cleanup
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("device busy")
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        if self.fail_cleanup:
            raise RuntimeError("stop problem")

    def close(self) -> None:
        self.closed = True
        if self.fail_cleanup:
            raise RuntimeError("close problem")


class FakeSoundDevice:
    def __init__(self, *, stream: FakeStream | None = None) -> None:
        self.default = SimpleNamespace(device=(0, -1))
        self.settings: dict[str, object] | None = None
        self.stream_kwargs: dict[str, object] | None = None
        self.stream = stream or FakeStream()

    @staticmethod
    def query_devices() -> list[dict[str, object]]:
        return [
            {
                "name": "袦懈泻褉芯褎芯薪 ?",
                "max_input_channels": 2,
                "default_samplerate": 48_000.0,
            }
        ]

    def check_input_settings(self, **kwargs: object) -> None:
        self.settings = kwargs

    def InputStream(self, **kwargs: object) -> FakeStream:  # noqa: N802 - mirrors library API
        self.stream_kwargs = kwargs
        return self.stream


def make_capture(
    audio_queue: queue.Queue[object] | None = None,
    *,
    sd: FakeSoundDevice | None = None,
) -> tuple[MicrophoneCapture, threading.Event, FakeSoundDevice]:
    fake_sd = sd or FakeSoundDevice()
    _, device = validate_live_input_device(0, sounddevice_module=fake_sd)
    event = threading.Event()
    capture = MicrophoneCapture(
        audio_queue or queue.Queue(maxsize=2),
        device=device,
        sounddevice_module=fake_sd,
        fatal_event=event,
        clock=lambda: 10.0,
    )
    capture.accepting = True
    return capture, event, fake_sd


def test_device_validation_checks_exact_native_format() -> None:
    sd = FakeSoundDevice()
    _, device = validate_live_input_device(None, sounddevice_module=sd)
    assert device.index == 0
    assert device.name == "袦懈泻褉芯褎芯薪 ?"
    assert sd.settings == {
        "device": 0,
        "channels": 1,
        "dtype": "float32",
        "samplerate": 16_000,
    }


def test_device_validation_rejects_unsupported_format() -> None:
    class BadSettings(FakeSoundDevice):
        def check_input_settings(self, **kwargs: object) -> None:
            raise RuntimeError("invalid sample rate")

    with pytest.raises(MicrophoneCaptureError, match="cannot open as mono float32"):
        validate_live_input_device(0, sounddevice_module=BadSettings())


def test_device_validation_rejects_missing_input() -> None:
    sd = FakeSoundDevice()
    sd.query_devices = lambda: []  # type: ignore[method-assign]
    with pytest.raises(AudioDeviceError, match="No audio input devices"):
        validate_live_input_device(None, sounddevice_module=sd)


def test_callback_copies_mono_block_and_preserves_sequence() -> None:
    audio_queue: queue.Queue[object] = queue.Queue(maxsize=2)
    capture, event, _ = make_capture(audio_queue)
    source = np.full((512, 1), 0.25, dtype=np.float32)
    capture.callback(source, 512, None, None)
    source.fill(0.9)
    block = audio_queue.get_nowait()
    assert isinstance(block, AudioBlock)
    assert block.sequence == 0
    assert block.sequence_number == 0
    assert block.started_at == pytest.approx(10.0 - BLOCK_SECONDS)
    assert block.captured_at == 10.0
    assert block.ended_at == 10.0
    assert np.all(block.samples == 0.25)
    assert not block.samples.flags.writeable
    assert not event.is_set()


def test_callback_ignores_data_when_capture_is_stopping() -> None:
    audio_queue: queue.Queue[object] = queue.Queue(maxsize=2)
    capture, event, _ = make_capture(audio_queue)
    capture.accepting = False
    capture.callback(np.zeros((512, 1), dtype=np.float32), 512, None, None)
    assert audio_queue.empty()
    assert capture.metrics.callbacks == 0
    assert not event.is_set()


@pytest.mark.parametrize(
    ("frames", "samples", "message"),
    [
        (256, np.zeros((256, 1), dtype=np.float32), "block size"),
        (512, np.zeros((512, 2), dtype=np.float32), "shape"),
        (512, np.zeros((512, 1), dtype=np.float64), "dtype"),
        (512, np.full((512, 1), np.nan, dtype=np.float32), "finite"),
    ],
)
def test_callback_rejects_invalid_blocks(
    frames: int,
    samples: np.ndarray,
    message: str,
) -> None:
    capture, event, _ = make_capture()
    capture.callback(samples, frames, None, None)
    assert event.is_set()
    assert message in (capture.fatal_error or "")
    assert capture.metrics.enqueued_blocks == 0


def test_queue_overflow_is_fatal_and_counted() -> None:
    audio_queue: queue.Queue[object] = queue.Queue(maxsize=1)
    audio_queue.put_nowait(object())
    capture, event, _ = make_capture(audio_queue)
    capture.callback(np.zeros((512, 1), dtype=np.float32), 512, None, None)
    assert event.is_set()
    assert capture.metrics.dropped_blocks == 1
    assert "continuity was lost" in (capture.fatal_error or "")


def test_queue_high_watermark_counts_enqueued_blocks() -> None:
    audio_queue: queue.Queue[object] = queue.Queue(maxsize=3)
    capture, _, _ = make_capture(audio_queue)
    samples = np.zeros((512, 1), dtype=np.float32)
    capture.callback(samples, 512, None, None)
    capture.callback(samples, 512, None, None)
    assert capture.metrics.enqueued_blocks == 2
    assert capture.metrics.queue_high_watermark == 2


def test_portaudio_input_overflow_is_fatal_and_not_enqueued() -> None:
    audio_queue: queue.Queue[object] = queue.Queue(maxsize=2)
    capture, event, _ = make_capture(audio_queue)
    capture.callback(
        np.zeros((512, 1), dtype=np.float32),
        512,
        None,
        FakeStatus("input overflow", input_overflow=True),
    )
    assert event.is_set()
    assert audio_queue.empty()
    assert capture.metrics.portaudio_status_count == 1
    assert capture.metrics.portaudio_status_texts == ["input overflow"]


def test_non_overflow_portaudio_status_is_recorded_with_block() -> None:
    audio_queue: queue.Queue[object] = queue.Queue(maxsize=2)
    capture, event, _ = make_capture(audio_queue)
    capture.callback(
        np.zeros((512, 1), dtype=np.float32),
        512,
        None,
        FakeStatus("priming output"),
    )
    block = audio_queue.get_nowait()
    assert isinstance(block, AudioBlock)
    assert block.portaudio_status == "priming output"
    assert capture.metrics.portaudio_status_count == 1
    assert not event.is_set()


def test_start_uses_exact_input_stream_settings_and_close_releases_it() -> None:
    capture, event, sd = make_capture()
    capture.accepting = False
    capture.start()
    assert sd.stream_kwargs is not None
    assert sd.stream_kwargs["device"] == 0
    assert sd.stream_kwargs["samplerate"] == 16_000
    assert sd.stream_kwargs["channels"] == 1
    assert sd.stream_kwargs["dtype"] == "float32"
    assert sd.stream_kwargs["blocksize"] == 512
    assert sd.stream_kwargs["callback"] == capture.callback
    capture.close()
    assert sd.stream.stopped and sd.stream.closed
    assert capture.closed and not capture.accepting
    assert not event.is_set()


def test_start_failure_is_user_facing_and_releases_stream() -> None:
    sd = FakeSoundDevice(stream=FakeStream(fail_start=True))
    capture, _, _ = make_capture(sd=sd)
    capture.accepting = False
    with pytest.raises(MicrophoneCaptureError, match="device busy"):
        capture.start()
    assert sd.stream.stopped and sd.stream.closed
    assert capture.closed


def test_cleanup_failures_become_fatal() -> None:
    sd = FakeSoundDevice(stream=FakeStream(fail_cleanup=True))
    capture, event, _ = make_capture(sd=sd)
    capture.stream = sd.stream
    capture.close()
    assert event.is_set()
    assert "stop failed" in (capture.fatal_error or "")
    assert "close failed" in (capture.fatal_error or "")


def test_audio_block_rejects_mutation_and_invalid_size() -> None:
    block = AudioBlock(0, np.zeros(512, dtype=np.float32), 0.0, 0.032)
    with pytest.raises(ValueError):
        block.samples[0] = 1.0
    with pytest.raises(ValueError, match="512"):
        AudioBlock(0, np.zeros(511, dtype=np.float32), 0.0, 0.032)


def test_callback_source_has_no_vad_disk_print_or_blocking_put() -> None:
    source = inspect.getsource(MicrophoneCapture.callback)
    assert "put_nowait" in source
    assert ".put(" not in source
    assert "speech_probability" not in source
    assert "wave" not in source
    assert "print(" not in source


def test_module_import_does_not_construct_an_input_stream() -> None:
    source = inspect.getsource(validate_live_input_device)
    assert "InputStream" not in source
