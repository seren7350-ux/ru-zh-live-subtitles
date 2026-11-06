from __future__ import annotations

import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_subtitles.diagnostic_logging import diagnostic_logger
from live_subtitles.gui.events import FatalErrorEvent, ListeningEvent, SegmentErrorEvent, StoppedEvent, SubtitleEvent
from live_subtitles.gui.process_controller import (
    LiveProcessOverlayController,
    LiveWorkerConfig,
    LiveWorkerSummary,
    ParentProcessEventQueue,
    ProcessEventTransport,
    ProcessStopSignal,
    _live_process_main,
)


@pytest.fixture(autouse=True)
def isolated_worker_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    logger = diagnostic_logger()
    original_handlers = logger.handlers[:]
    logger.handlers = []
    yield
    for handler in logger.handlers:
        handler.close()
    logger.handlers = original_handlers


def config() -> LiveWorkerConfig:
    return LiveWorkerConfig(
        device_index=1,
        duration=1.0,
        audio_queue_size=16,
        segment_queue_size=8,
        vad_threshold=0.5,
        negative_threshold=0.35,
        min_silence_ms=600,
        speech_pad_ms=100,
        pre_roll_ms=250,
        min_segment_ms=300,
        max_segment_seconds=15.0,
        asr_model="fake-asr",
        asr_provider="CPUExecutionProvider",
        translation_engine="nllb",
        translation_model="fake-nllb",
        translation_device="cuda",
        num_beams=1,
        max_new_tokens=64,
    )


class FakeTransport:
    def __init__(self) -> None:
        self.items: list[object] = []
        self.reader = SimpleNamespace(close=lambda: None)
        self.writer = SimpleNamespace(close=lambda: None)

    def put(self, event: object) -> bool:
        self.items.append(event)
        return True

    def put_summary(self, summary: LiveWorkerSummary) -> None:
        self.items.append(summary)


def fake_result() -> SimpleNamespace:
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
        session_seconds=1.0,
        portaudio_status_count=0,
    )
    subtitle_metrics = SimpleNamespace(
        successful_segments=1,
        failed_segments=0,
        queue_high_watermark=1,
        queue_capacity=8,
        worker_exited=True,
    )
    segment = SimpleNamespace(
        succeeded=True,
        index=1,
        russian_text="Привет",
        chinese_text="你好",
        audio_duration_seconds=1.0,
        russian_latency_seconds=0.2,
        chinese_latency_seconds=0.4,
        start_seconds=4.25,
        end_seconds=5.25,
        error_stage=None,
        error=None,
    )
    return SimpleNamespace(
        succeeded=True,
        errors=(),
        vad=SimpleNamespace(metrics=vad_metrics, stop_reason="duration elapsed"),
        subtitles=(segment,),
        subtitle_metrics=subtitle_metrics,
        prepare_metrics=SimpleNamespace(total_prepare_seconds=0.5),
    )


class FakeSession:
    def __init__(self, on_result: object, on_listening: object) -> None:
        self.on_result = on_result
        self.on_listening = on_listening
        self.stop_reasons: list[str] = []
        self.pipeline = SimpleNamespace(
            recognizer=SimpleNamespace(model_load_count=1, model_load_seconds=0.2),
            translator=SimpleNamespace(
                actual_device="cuda",
                requested_device="cuda",
                dtype="float16",
                tokenizer_load_count=1,
                model_load_count=1,
                total_load_seconds=0.3,
                peak_cuda_memory_bytes=1024,
            ),
        )
        self.vad_session = SimpleNamespace(
            device=SimpleNamespace(name="Fake microphone"),
            vad=SimpleNamespace(load_seconds=0.1, session_creation_count=1),
        )

    @staticmethod
    def prepare() -> SimpleNamespace:
        return SimpleNamespace(
            asr_prepare_seconds=0.2,
            translation_prepare_seconds=0.3,
            total_prepare_seconds=0.5,
        )

    def run(self) -> SimpleNamespace:
        result = fake_result()
        if not self.stop_reasons:
            self.on_listening()
            self.on_result(result.subtitles[0])
        return result

    def request_stop(self, reason: str) -> None:
        self.stop_reasons.append(reason)


def test_process_worker_emits_events_and_compact_summary() -> None:
    transport = FakeTransport()
    stop = threading.Event()
    holder: dict[str, FakeSession] = {}

    def build(_config: object, on_result: object, on_listening: object) -> FakeSession:
        holder["session"] = FakeSession(on_result, on_listening)
        return holder["session"]

    _live_process_main(config(), transport, stop, build)  # type: ignore[arg-type]
    assert any(isinstance(item, ListeningEvent) for item in transport.items)
    assert any(isinstance(item, SubtitleEvent) for item in transport.items)
    subtitle = next(item for item in transport.items if isinstance(item, SubtitleEvent))
    assert (subtitle.start_seconds, subtitle.end_seconds) == (4.25, 5.25)
    assert any(isinstance(item, StoppedEvent) for item in transport.items)
    summary = next(item for item in transport.items if isinstance(item, LiveWorkerSummary))
    assert summary.asr_model_load_count == 1
    assert summary.result.subtitles[0].russian_text == "Привет"


def test_exit_during_prepare_never_emits_listening() -> None:
    transport = FakeTransport()
    stop = threading.Event()
    stop.set()
    holder: dict[str, FakeSession] = {}

    def build(_config: object, on_result: object, on_listening: object) -> FakeSession:
        holder["session"] = FakeSession(on_result, on_listening)
        return holder["session"]

    _live_process_main(config(), transport, stop, build)  # type: ignore[arg-type]
    assert holder["session"].stop_reasons
    assert not any(isinstance(item, ListeningEvent) for item in transport.items)


class FakeValue:
    def __init__(self, value: int) -> None:
        self.value = value


class FakeProcess:
    def __init__(self, **_kwargs: object) -> None:
        self.alive = False
        self.closed = False
        self.pid = 123
        self.exitcode = 0
        self.terminate_calls = 0
        self.kill_calls = 0

    def start(self) -> None:
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float) -> None:
        assert timeout == 0

    def close(self) -> None:
        self.closed = True

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1


class FakeContext:
    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []
        self.process_kwargs: list[dict[str, object]] = []

    @staticmethod
    def Pipe(duplex: bool):
        return multiprocessing.get_context("spawn").Pipe(duplex=duplex)

    @staticmethod
    def RawValue(_kind: str, value: int) -> FakeValue:
        return FakeValue(value)

    @staticmethod
    def Event() -> threading.Event:
        return threading.Event()

    def Process(self, **kwargs: object) -> FakeProcess:
        assert kwargs["name"] == "subtitle-overlay-live-process"
        self.process_kwargs.append(dict(kwargs))
        process = FakeProcess(**kwargs)
        self.processes.append(process)
        return process


def test_process_controller_prevents_concurrent_start_and_restarts_cleanly() -> None:
    context = FakeContext()
    controller = LiveProcessOverlayController(config(), context=context)
    assert controller.start()
    assert not controller.start()
    controller.request_stop()
    assert controller._stop_signal.is_set()
    context.processes[0].alive = False
    controller._stop_signal._flag.value = 0
    controller.request_stop()
    assert not controller._stop_signal.is_set()
    wait_for_exit(controller)
    assert controller.start()
    assert context.processes[0].closed
    assert len(context.processes) == 2


def test_set_device_index_rejects_running_controller_without_mutation() -> None:
    context = FakeContext()
    controller = LiveProcessOverlayController(config(), context=context)
    assert controller.start()
    original = controller.config
    assert not controller.set_device_index(9)
    assert controller.config is original
    assert controller.config.device_index == 1


def test_set_device_index_replaces_only_device_field_while_stopped() -> None:
    controller = LiveProcessOverlayController(config(), context=FakeContext())
    original = asdict(controller.config)
    assert controller.set_device_index(9)
    updated = asdict(controller.config)
    assert updated.pop("device_index") == 9
    assert original.pop("device_index") == 1
    assert updated == original


def test_restart_passes_latest_device_index_to_new_child_process() -> None:
    context = FakeContext()
    controller = LiveProcessOverlayController(config(), context=context)
    assert controller.start()
    first_args = context.process_kwargs[0]["args"]
    assert isinstance(first_args, tuple)
    assert first_args[0].device_index == 1
    context.processes[0].alive = False
    wait_for_exit(controller)
    assert controller.set_device_index(7)
    assert controller.start()
    second_args = context.process_kwargs[1]["args"]
    assert isinstance(second_args, tuple)
    assert second_args[0].device_index == 7


def _spawn_emit_stopped(transport: ProcessEventTransport) -> None:
    transport.reader.close()
    transport.put(StoppedEvent("spawn test complete", time.perf_counter()))
    transport.writer.close()


def test_real_spawn_transport_remains_drainable_after_worker_exit() -> None:
    context = multiprocessing.get_context("spawn")
    transport = ProcessEventTransport(context, capacity=8)
    summaries: list[LiveWorkerSummary] = []
    events = ParentProcessEventQueue(transport, summaries.append)
    process = context.Process(target=_spawn_emit_stopped, args=(transport,))
    process.start()
    events.start_receiver()
    received: list[object] = []
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and (process.is_alive() or not events.settled):
        received.extend(events.drain())
        time.sleep(0.01)
    process.join(timeout=5.0)
    received.extend(events.drain())
    assert not process.is_alive()
    assert any(isinstance(event, StoppedEvent) for event in received)
    assert events.drain() == ()
    process.close()
    events.discard()


def wait_for_exit(controller: LiveProcessOverlayController, timeout: float = 10.0) -> list[object]:
    received: list[object] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        received.extend(controller.events.drain())
        received.extend(controller.poll_process())
        if controller.shutdown_complete:
            return received
        time.sleep(0.005)
    raise AssertionError("Worker did not finish or its event receiver did not settle.")


def _spawn_normal(_config, transport, _signal) -> None:
    _spawn_emit_stopped(transport)


def _spawn_crash(_config, transport, _signal) -> None:
    transport.reader.close()
    transport.put(ListeningEvent("fake device", time.perf_counter()))
    os._exit(17)


def _spawn_silent(_config, transport, _signal) -> None:
    transport.reader.close()
    transport.writer.close()


def _spawn_hang(_config, transport, _signal) -> None:
    transport.reader.close()
    transport.put(ListeningEvent("fake device", time.perf_counter()))
    while True:
        time.sleep(0.01)


def _spawn_large_frame(_config, transport, _signal) -> None:
    transport.reader.close()
    payload = "x" * (32 * 1024 * 1024)
    transport.put(ListeningEvent("fake device", time.perf_counter()))
    while True:
        transport.writer.send(SubtitleEvent(1, payload, "", 1.0, None, None, time.perf_counter()))


def _spawn_session(config, transport, stop_signal) -> None:
    _live_process_main(config, transport, stop_signal, _build_fake_session)


def _build_fake_session(_config, on_result, on_listening):
    return FakeSession(on_result, on_listening)


def _spawn_concurrent_frames(config, transport, stop_signal) -> None:
    transport.reader.close()
    captured = FakeTransport()
    _live_process_main(config, captured, stop_signal, _build_fake_session)
    frames = [
        item for item in captured.items
        if isinstance(item, (SubtitleEvent, StoppedEvent, LiveWorkerSummary))
    ]
    barrier = threading.Barrier(len(frames))
    send = transport.writer.send
    writing = threading.Lock()

    def slow_send(frame):
        # Make overlapping sends observable even on pipes that write small frames atomically.
        assert writing.acquire(blocking=False), "Concurrent pipe writes"
        try:
            time.sleep(0.05)
            send(frame)
        finally:
            writing.release()

    def publish(frame):
        barrier.wait(timeout=5.0)
        if isinstance(frame, LiveWorkerSummary):
            transport.put_summary(frame)
        else:
            assert transport.put(frame)

    transport.writer.send = slow_send
    try:
        with ThreadPoolExecutor(max_workers=len(frames)) as pool:
            list(pool.map(publish, frames))
    finally:
        transport.writer.close()


def reap(controller: LiveProcessOverlayController) -> None:
    if controller.running:
        controller.kill()
    wait_for_exit(controller)
    controller.dispose()


@pytest.mark.parametrize("target, code", [(_spawn_crash, 17), (_spawn_silent, 0)])
def test_real_spawn_missing_completion_reports_exitcode_once_and_restarts(target, code) -> None:
    controller = LiveProcessOverlayController(config(), process_target=target)
    try:
        assert controller.start()
        first_events = controller.events
        received = wait_for_exit(controller)
        fatals = [event for event in received if isinstance(event, FatalErrorEvent)]
        assert len(fatals) == 1
        assert f"exitcode={code}" in fatals[0].message
        assert controller.last_exitcode == code
        assert controller.poll_process() == ()
        controller.process_target = _spawn_normal
        assert controller.start()
        assert controller.events is not first_events
        assert controller.events.fatal_message is None
        second = wait_for_exit(controller)
        assert not any(isinstance(event, FatalErrorEvent) for event in second)
        assert any(isinstance(event, StoppedEvent) for event in second)
    finally:
        reap(controller)


def test_real_spawn_session_drains_final_summary_before_marking_complete() -> None:
    controller = LiveProcessOverlayController(config(), process_target=_spawn_session)
    try:
        assert controller.start()
        received = wait_for_exit(controller)
        assert not any(isinstance(event, FatalErrorEvent) for event in received)
        assert any(isinstance(event, SubtitleEvent) for event in received)
        assert controller.last_summary is not None
        assert controller.last_summary.asr_model_load_count == 1
        assert controller.last_exitcode == 0
        assert controller.events.settled
    finally:
        reap(controller)


def test_real_spawn_serializes_event_and_summary_sends_across_worker_threads() -> None:
    controller = LiveProcessOverlayController(config(), process_target=_spawn_concurrent_frames)
    try:
        assert controller.start()
        received = wait_for_exit(controller)
        assert controller.last_exitcode == 0
        assert not any(isinstance(event, FatalErrorEvent) for event in received)
        assert [event.chinese_text for event in received if isinstance(event, SubtitleEvent)] == ["你好"]
        assert len(controller.summaries) == 1
        assert controller.summaries[0].result.subtitles[0].russian_text == "Привет"
        assert controller.events.enqueued == controller.events.dequeued == 2
        assert controller.events.overflow_count == 0
        assert controller.events.settled
    finally:
        reap(controller)


@pytest.mark.parametrize("target", [_spawn_hang, _spawn_large_frame])
def test_hard_stop_never_reads_pipe_on_polling_thread_and_receiver_finishes(target) -> None:
    controller = LiveProcessOverlayController(config(), process_target=target)
    try:
        assert controller.start()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if any(isinstance(event, ListeningEvent) for event in controller.events.drain()):
                break
            time.sleep(0.005)
        else:
            pytest.fail("Worker did not announce readiness")
        started = time.monotonic()
        controller.request_stop("test hard stop")
        controller.terminate()
        controller.terminate()
        events = list(controller.poll_process())
        assert time.monotonic() - started < 1.0
        events.extend(wait_for_exit(controller))
        assert controller.events.reader_finished
        assert controller.last_exitcode != 0
        assert any(isinstance(event, FatalErrorEvent) for event in events)
    finally:
        reap(controller)


def test_terminate_and_kill_are_idempotent_and_dispose_waits_for_process() -> None:
    context = FakeContext()
    controller = LiveProcessOverlayController(config(), context=context)
    controller.start()
    process = context.processes[0]
    controller.terminate()
    controller.terminate()
    controller.kill()
    controller.kill()
    controller.dispose()
    assert process.terminate_calls == process.kill_calls == 1
    assert not process.closed
    process.alive = False
    wait_for_exit(controller)
    controller.dispose()
    assert process.closed
    assert controller._process is None


def test_spawn_failure_closes_pipe_handles_and_can_retry() -> None:
    context = FakeContext()
    original = context.Process

    def fail_process(**kwargs):
        process = original(**kwargs)
        process.start = lambda: (_ for _ in ()).throw(OSError("spawn unavailable"))
        return process

    context.Process = fail_process
    controller = LiveProcessOverlayController(config(), context=context)
    with pytest.raises(OSError, match="spawn unavailable"):
        controller.start()
    assert controller.transport.reader.closed
    assert controller.transport.writer.closed
    assert context.processes[0].closed
    context.Process = original
    assert controller.start()
    context.processes[-1].alive = False
    wait_for_exit(controller)
    controller.dispose()


def test_stop_signal_can_be_set_before_worker_waits() -> None:
    signal = ProcessStopSignal(multiprocessing.get_context("spawn"))
    signal.set()
    signal.wait()
    assert signal.is_set()


def test_worker_redacts_known_caption_before_sending_error_to_parent() -> None:
    transport = FakeTransport()
    sensitive = "Секретный текст лекции"

    class FailingSession(FakeSession):
        def run(self):
            result = fake_result()
            segment = result.subtitles[0]
            segment.succeeded = False
            segment.russian_text = sensitive
            segment.error_stage = "translation"
            segment.error = f"Cannot translate {sensitive!r}"
            self.on_result(segment)
            return result

    _live_process_main(
        config(), transport, threading.Event(),
        lambda _config, on_result, on_listening: FailingSession(on_result, on_listening),
    )
    event = next(event for event in transport.items if isinstance(event, SegmentErrorEvent))
    assert sensitive not in event.message
    assert "<redacted-caption>" in event.message
