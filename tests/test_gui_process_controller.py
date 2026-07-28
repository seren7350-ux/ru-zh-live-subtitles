from __future__ import annotations

import queue
import multiprocessing
import threading
import time
from dataclasses import asdict
from types import SimpleNamespace

from live_subtitles.gui.events import ListeningEvent, StoppedEvent, SubtitleEvent
from live_subtitles.gui.process_controller import (
    LiveProcessOverlayController,
    LiveWorkerConfig,
    LiveWorkerSummary,
    ParentProcessEventQueue,
    ProcessEventTransport,
    _live_process_main,
)


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
        self.queue = SimpleNamespace(close=lambda: None, join_thread=lambda: None)

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

    def start(self) -> None:
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float) -> None:
        assert timeout == 0

    def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []
        self.process_kwargs: list[dict[str, object]] = []

    @staticmethod
    def Queue(maxsize: int) -> queue.Queue[object]:
        return queue.Queue(maxsize=maxsize)

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
    controller._stop_signal.clear()
    controller.request_stop()
    assert not controller._stop_signal.is_set()
    assert controller.start()
    assert context.processes[0].closed
    assert len(context.processes) == 2


def test_set_device_index_rejects_running_controller_without_mutation() -> None:
    context = FakeContext()
    controller = LiveProcessOverlayController(config(), context=context)
    original = controller.config
    assert controller.start()
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
    assert controller.set_device_index(7)
    assert controller.start()
    second_args = context.process_kwargs[1]["args"]
    assert isinstance(second_args, tuple)
    assert second_args[0].device_index == 7


def _spawn_emit_stopped(transport: ProcessEventTransport) -> None:
    transport.put(StoppedEvent("spawn test complete", time.perf_counter()))
    transport.queue.close()
    transport.queue.join_thread()


def test_real_spawn_transport_remains_drainable_after_worker_exit() -> None:
    context = multiprocessing.get_context("spawn")
    transport = ProcessEventTransport(context, capacity=8)
    summaries: list[LiveWorkerSummary] = []
    events = ParentProcessEventQueue(transport, summaries.append)
    process = context.Process(target=_spawn_emit_stopped, args=(transport,))
    process.start()
    received: list[object] = []
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and (process.is_alive() or not received):
        received.extend(events.drain())
        time.sleep(0.01)
    process.join(timeout=5.0)
    received.extend(events.drain())
    assert not process.is_alive()
    assert any(isinstance(event, StoppedEvent) for event in received)
    assert events.drain() == ()
    process.close()
    transport.queue.close()
    transport.queue.join_thread()
