from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from live_subtitles.gui.controller import (
    DemoOverlayController,
    GuiEventQueue,
    GuiMetrics,
    LiveOverlayController,
    sanitize_message,
)
from live_subtitles.gui.events import (
    FatalErrorEvent,
    PreparingEvent,
    SegmentErrorEvent,
    StoppedEvent,
    SubtitleEvent,
)


def wait_finished(controller: object) -> None:
    deadline = time.monotonic() + 2.0
    while getattr(controller, "running") and time.monotonic() < deadline:
        time.sleep(0.005)
    assert not getattr(controller, "running")


def test_event_queue_is_bounded_and_ordered() -> None:
    events = GuiEventQueue(8)
    for index in range(8):
        assert events.put(PreparingEvent(str(index), float(index)))
    assert not events.put(PreparingEvent("overflow", 9.0))
    assert [event.message for event in events.drain()] == [str(index) for index in range(8)]
    assert events.high_watermark == 8
    assert events.overflow_count == 1
    assert events.fatal_message is not None


def test_metrics_calculate_median_p95_and_remain_bounded() -> None:
    metrics = GuiMetrics(GuiEventQueue())
    for value in range(9_000):
        metrics.render_latencies.add(float(value))
    snapshot = metrics.snapshot()
    assert metrics.render_latencies.retained_count == 8_192
    assert snapshot.average_render_latency_seconds == pytest.approx(4_499.5)
    assert snapshot.p95_render_latency_seconds > snapshot.median_render_latency_seconds


def fake_result(*, succeeded: bool = True) -> SimpleNamespace:
    vad_metrics = SimpleNamespace(
        captured_blocks=2,
        processed_blocks=2,
        detected_segments=1,
        dropped_blocks=0,
        sequence_gaps=0,
        queue_high_watermark=1,
        queue_capacity=16,
        microphone_closed=True,
        worker_exited=True,
    )
    subtitle_metrics = SimpleNamespace(
        successful_segments=int(succeeded),
        failed_segments=int(not succeeded),
        queue_high_watermark=1,
        queue_capacity=8,
        worker_exited=True,
    )
    return SimpleNamespace(
        succeeded=succeeded,
        errors=() if succeeded else ("synthetic fatal",),
        vad=SimpleNamespace(metrics=vad_metrics, stop_reason="duration elapsed"),
        subtitle_metrics=subtitle_metrics,
    )


class FakeSession:
    def __init__(self, on_result: object, on_listening: object) -> None:
        self.on_result = on_result
        self.on_listening = on_listening
        self.stop_reasons: list[str] = []
        self.pipeline = SimpleNamespace(
            translator=SimpleNamespace(actual_device="cpu", requested_device="cpu")
        )
        self.vad_session = SimpleNamespace(
            device=SimpleNamespace(name="Fake microphone"),
            vad=SimpleNamespace(load_seconds=0.1),
        )

    @staticmethod
    def prepare() -> SimpleNamespace:
        return SimpleNamespace(
            asr_prepare_seconds=0.2,
            translation_prepare_seconds=0.3,
            total_prepare_seconds=0.5,
        )

    def run(self) -> SimpleNamespace:
        self.on_listening()
        self.on_result(
            SimpleNamespace(
                succeeded=True,
                index=1,
                russian_text="Привет",
                chinese_text="你好",
                audio_duration_seconds=1.0,
                russian_latency_seconds=0.2,
                chinese_latency_seconds=0.4,
                error_stage=None,
                error=None,
            )
        )
        return fake_result()

    def request_stop(self, reason: str) -> None:
        self.stop_reasons.append(reason)


def test_controller_callbacks_only_enqueue_immutable_events() -> None:
    holder: dict[str, FakeSession] = {}
    release = threading.Event()

    class PausedSession(FakeSession):
        def run(self) -> SimpleNamespace:
            release.wait(1.0)
            return super().run()

    def factory(on_result: object, on_listening: object) -> FakeSession:
        holder["session"] = PausedSession(on_result, on_listening)
        return holder["session"]

    controller = LiveOverlayController(factory)
    assert controller.start()
    assert not controller.start()
    release.set()
    wait_finished(controller)
    events = controller.events.drain()
    assert isinstance(events[0], PreparingEvent)
    assert any(isinstance(event, SubtitleEvent) for event in events)
    assert isinstance(events[-1], StoppedEvent)


def test_failed_segment_becomes_segment_error_event() -> None:
    controller = LiveOverlayController(lambda *_args: None)  # type: ignore[arg-type]
    controller._on_result(
        SimpleNamespace(
            succeeded=False,
            index=3,
            error_stage="translation",
            error="failed",
        )
    )
    event = controller.events.drain()[0]
    assert isinstance(event, SegmentErrorEvent)
    assert event.index == 3


def test_queue_overflow_requests_session_stop() -> None:
    controller = LiveOverlayController(lambda *_args: None, event_queue=GuiEventQueue(8))  # type: ignore[arg-type]
    session = SimpleNamespace(stop_reasons=[])
    session.request_stop = lambda reason: session.stop_reasons.append(reason)
    controller._session = session
    for index in range(8):
        controller._emit(PreparingEvent(str(index), 0.0))
    controller._emit(PreparingEvent("overflow", 0.0))
    assert session.stop_reasons == ["GUI event queue overflow"]


def test_stop_during_prepare_is_pending_and_forwarded() -> None:
    entered = threading.Event()
    release = threading.Event()
    holder: dict[str, FakeSession] = {}

    class BlockingSession(FakeSession):
        def prepare(self) -> SimpleNamespace:
            entered.set()
            release.wait(1.0)
            return super().prepare()

    def factory(on_result: object, on_listening: object) -> BlockingSession:
        holder["session"] = BlockingSession(on_result, on_listening)
        return holder["session"]

    controller = LiveOverlayController(factory)
    controller.start()
    assert entered.wait(1.0)
    controller.close()
    release.set()
    wait_finished(controller)
    assert "window closed" in holder["session"].stop_reasons


def test_sanitizer_removes_home_and_temp_paths() -> None:
    from pathlib import Path
    import tempfile

    message = sanitize_message(
        f"bad {Path.home()} and {tempfile.gettempdir()} token hf_abcdefghijkl"
    )
    assert str(Path.home()).lower() not in message.lower()
    assert "<home>" in message
    assert "hf_abcdefghijkl" not in message


def test_demo_emits_events_without_live_session_dependencies() -> None:
    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleeper(seconds: float) -> None:
        now[0] += seconds

    controller = DemoOverlayController(duration=4.1, clock=clock, sleeper=sleeper)
    controller.start()
    wait_finished(controller)
    events = controller.events.drain()
    assert any(isinstance(event, SubtitleEvent) for event in events)
    assert any(isinstance(event, SegmentErrorEvent) for event in events)
    assert not any(isinstance(event, FatalErrorEvent) for event in events)


def test_zero_duration_demo_runs_until_explicit_stop() -> None:
    now = [0.0]
    holder: dict[str, DemoOverlayController] = {}

    def clock() -> float:
        return now[0]

    def sleeper(seconds: float) -> None:
        now[0] += seconds
        if now[0] >= 2.2:
            holder["controller"].request_stop()

    controller = DemoOverlayController(duration=0, clock=clock, sleeper=sleeper)
    holder["controller"] = controller
    controller.start()
    wait_finished(controller)
    events = controller.events.drain()
    assert any(isinstance(event, SubtitleEvent) for event in events)
    assert isinstance(events[-1], StoppedEvent)
