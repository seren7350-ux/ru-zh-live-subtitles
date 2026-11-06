from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_subtitles.audio.recording import AudioDevice, AudioDeviceError
from live_subtitles import diagnostic_logging
from live_subtitles.cli import build_parser, main
from live_subtitles.gui import app
from live_subtitles.gui.controller import GuiEventQueue, GuiMetrics
from live_subtitles.gui.events import FatalErrorEvent, SegmentErrorEvent, StoppedEvent, SubtitleEvent
from live_subtitles.gui.microphone_selector import MicrophoneSelectorModel
from live_subtitles.model_assets import (
    ModelAssetsReport,
    ModelAssetStatus,
)
from live_subtitles.gui.state import SubtitleViewState


class FakeOverlay:
    def __init__(self, _root: object, _state: object, **callbacks: object) -> None:
        self.callbacks = callbacks
        self.render_count = 0
        self.running_states: list[tuple[bool, bool]] = []
        self.settings_panel = None
        self.state = _state
        self.running = False
        self.closing = False
        self.on_start = callbacks["on_start"]
        self.on_stop = callbacks["on_stop"]

    def render(self) -> None:
        self.render_count += 1

    def set_running(self, running: bool, *, closing: bool = False) -> None:
        self.running_states.append((running, closing))
        self.running = running
        self.closing = closing
        self.render()


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []
        self.destroyed = False

    def after(self, delay: int, callback: object) -> None:
        self.after_calls.append((delay, callback))

    def destroy(self) -> None:
        self.destroyed = True


class FakeController:
    def __init__(self) -> None:
        self.running = False
        self.events = GuiEventQueue()
        self.metrics = GuiMetrics(self.events)
        self.started = 0
        self.stop_reasons: list[str] = []
        self.device_indexes: list[int | None] = []
        self.pending_events: list[object] = []
        self.terminated = 0
        self.killed = 0
        self.disposed = 0
        self.tail_pending = False

    @property
    def shutdown_complete(self) -> bool:
        return not self.running and not self.tail_pending

    def poll_process(self) -> tuple[object, ...]:
        events = tuple(self.pending_events)
        self.pending_events.clear()
        return events

    def terminate(self) -> None:
        self.terminated += 1

    def kill(self) -> None:
        self.killed += 1

    def dispose(self) -> None:
        self.disposed += 1

    def start(self) -> bool:
        if self.running:
            return False
        self.running = True
        self.started += 1
        return True

    def request_stop(self, reason: str) -> None:
        self.stop_reasons.append(reason)

    def close(self) -> None:
        self.stop_reasons.append("window closed")

    def set_device_index(self, device_index: int | None) -> bool:
        if self.running:
            return False
        self.device_indexes.append(device_index)
        return True


@pytest.fixture
def isolated_subtitle_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(app, "subtitle_directory", lambda: tmp_path / "subtitles")
    return tmp_path / "subtitles"


@pytest.fixture(autouse=True)
def use_isolated_subtitle_directory(isolated_subtitle_directory: Path) -> None:
    pass


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[app.GuiRuntime, FakeRoot, FakeController]:
    monkeypatch.setattr(app, "SubtitleOverlay", FakeOverlay)
    root = FakeRoot()
    controller = FakeController()
    return app.GuiRuntime(root, SubtitleViewState(), controller, ui_poll_ms=50), root, controller


def test_gui_module_import_does_not_create_tk_root() -> None:
    sources = "\n".join(
        Path(module.__file__).read_text(encoding="utf-8")
        for module in (__import__("live_subtitles.gui.events", fromlist=["x"]), __import__("live_subtitles.gui.state", fromlist=["x"]), __import__("live_subtitles.gui.controller", fromlist=["x"]))
    )
    assert "tk.Tk()" not in sources
    assert "import tkinter" not in sources


@pytest.mark.parametrize("command", ["overlay-demo", "live-overlay"])
def test_gui_command_help_starts_without_window(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([command, "--help"])
    assert exc_info.value.code == 0
    assert "usage:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["overlay-demo", "--opacity", "-0.01"],
        ["overlay-demo", "--text-opacity", "1.01"],
        ["overlay-demo", "--history-lines", "101"],
        ["overlay-demo", "--chinese-font-size", "10"],
        ["overlay-demo", "--russian-font-size", "99"],
        ["overlay-demo", "--ui-poll-ms", "10"],
    ],
)
def test_gui_cli_bounds_are_enforced(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_gui_cli_accepts_independent_opacity_extremes_and_outline() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "overlay-demo", "--background-opacity", "0", "--text-opacity", "1", "--text-outline",
    ])
    state = app._state_from_args(args)
    assert state.background_opacity == 0 and state.text_opacity == 1 and state.text_outline
    args = parser.parse_args(["overlay-demo", "--opacity", "1", "--text-opacity", "0", "--no-text-outline"])
    state = app._state_from_args(args)
    assert state.background_opacity == 1 and state.text_opacity == 0 and not state.text_outline


def test_start_does_not_duplicate_background_session(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, _root, controller = runtime
    gui.start()
    gui.start()
    assert controller.started == 1


def test_live_runtime_uses_cli_selection_for_first_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "SubtitleOverlay", FakeOverlay)
    root = FakeRoot()
    controller = FakeController()
    resolved: list[int | None] = []

    def resolve(index: int | None) -> AudioDevice:
        resolved.append(index)
        return AudioDevice(6, "Input", 1, 48_000.0, True)

    selector = MicrophoneSelectorModel(6, resolve_device=resolve)
    gui = app.GuiRuntime(
        root,
        SubtitleViewState(),
        controller,
        ui_poll_ms=50,
        microphone_selector=selector,
    )
    gui.start()
    assert resolved == [6]
    assert controller.device_indexes == [6]
    assert controller.started == 1


def test_system_default_is_initial_selection_when_cli_device_is_omitted() -> None:
    args = build_parser().parse_args(["live-overlay"])
    assert args.device is None


def test_live_overlay_passes_cli_device_to_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[MicrophoneSelectorModel | None] = []

    class Controller:
        def __init__(self, _config: object) -> None:
            self.summaries: list[object] = []
            self.last_result = None

    def run_tk(
        _state: object,
        _controller: object,
        _args: object,
        *,
        microphone_selector: MicrophoneSelectorModel | None = None,
        model_assets: object | None = None,
    ) -> int:
        captured.append(microphone_selector)
        return 0

    monkeypatch.setattr(app, "LiveProcessOverlayController", Controller)
    monkeypatch.setattr(app, "_run_tk", run_tk)
    monkeypatch.setattr(app, "_log_live_exit_metrics", lambda _controller: None)
    args = build_parser().parse_args(["live-overlay", "--device", "12"])
    assert app._live_overlay(args) == 0
    assert captured[0] is not None
    assert captured[0].selected_index == 12


def test_overlay_demo_has_no_microphone_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[MicrophoneSelectorModel | None] = []

    def run_tk(
        _state: object,
        _controller: object,
        _args: object,
        *,
        microphone_selector: MicrophoneSelectorModel | None = None,
        model_assets: object | None = None,
    ) -> int:
        captured.append(microphone_selector)
        return 0

    monkeypatch.setattr(app, "_run_tk", run_tk)
    args = build_parser().parse_args(["overlay-demo"])
    assert app._overlay_demo(args) == 0
    assert captured == [None]


class FakeModelAssets:
    def __init__(self, reports: list[ModelAssetsReport]) -> None:
        self.reports = reports
        self.index = 0
        self.refresh_count = 0

    def refresh(self) -> ModelAssetsReport:
        self.refresh_count += 1
        report = self.reports[min(self.index, len(self.reports) - 1)]
        self.index += 1
        return report

    def snapshot(self) -> ModelAssetsReport:
        return self.reports[min(max(self.index - 1, 0), len(self.reports) - 1)]


def model_report(tmp_path: Path, *, ready: bool) -> ModelAssetsReport:
    status = ModelAssetStatus(
        key="nllb",
        model_id="facebook/nllb-200-distilled-600M",
        revision="f" * 40,
        ready=ready,
        location=tmp_path / "snapshot",
        cache_root=tmp_path / "hub",
        missing_files=() if ready else ("pytorch_model.bin",),
    )
    return ModelAssetsReport(tmp_path / "models", tmp_path / "hub", (status,))


def test_missing_models_block_start_without_worker_or_microphone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(app, "SubtitleOverlay", FakeOverlay)
    controller = FakeController()
    models = FakeModelAssets([model_report(tmp_path, ready=False)])
    gui = app.GuiRuntime(
        FakeRoot(),
        SubtitleViewState(),
        controller,
        ui_poll_ms=50,
        model_assets=models,  # type: ignore[arg-type]
        offline=True,
    )
    gui.start()
    assert controller.started == 0
    assert controller.device_indexes == []
    assert gui.state.status == "Model setup required"
    assert "pinned" not in gui.state.latest_error.lower()
    assert "not included" in gui.state.latest_error


def test_recheck_success_allows_next_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(app, "SubtitleOverlay", FakeOverlay)
    controller = FakeController()
    models = FakeModelAssets(
        [model_report(tmp_path, ready=False), model_report(tmp_path, ready=True)]
    )
    gui = app.GuiRuntime(
        FakeRoot(),
        SubtitleViewState(),
        controller,
        ui_poll_ms=50,
        model_assets=models,  # type: ignore[arg-type]
        offline=True,
    )
    gui.start()
    assert controller.started == 1
    assert gui.state.preparing


def test_offline_cli_boolean_options() -> None:
    parser = build_parser()
    assert parser.parse_args(["live-overlay", "--offline"]).offline is True
    assert parser.parse_args(["live-overlay", "--no-offline"]).offline is False


def test_invalid_microphone_blocks_start_before_preparing_or_process_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "SubtitleOverlay", FakeOverlay)
    root = FakeRoot()
    controller = FakeController()

    def reject(_index: int | None) -> AudioDevice:
        raise AudioDeviceError("Input device 99 is unavailable.")

    gui = app.GuiRuntime(
        root,
        SubtitleViewState(),
        controller,
        ui_poll_ms=50,
        microphone_selector=MicrophoneSelectorModel(99, resolve_device=reject),
    )
    gui.start()
    assert controller.started == 0
    assert controller.device_indexes == []
    assert gui.state.status == "Ready"
    assert not gui.state.preparing
    assert "selected microphone" in gui.state.latest_error
    assert gui.overlay.running_states[-1] == (False, False)


def test_device_change_is_rejected_while_running_and_applies_after_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "SubtitleOverlay", FakeOverlay)
    controller = FakeController()
    selector = MicrophoneSelectorModel(1)
    gui = app.GuiRuntime(
        FakeRoot(),
        SubtitleViewState(),
        controller,
        ui_poll_ms=50,
        microphone_selector=selector,
    )
    controller.running = True
    gui.select_microphone(2)
    assert selector.selected_index == 1
    controller.running = False
    gui.state.set_status("Stopped")
    gui.select_microphone(2)
    assert selector.selected_index == 2
    assert controller.device_indexes == [2]


def test_stop_requests_nonfatal_stop(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, _root, controller = runtime
    controller.running = True
    gui.stop()
    assert controller.stop_reasons == ["user requested stop"]
    assert gui.state.status == "Stopping..."


def test_close_is_nonblocking_and_uses_after(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, root, controller = runtime
    controller.running = True
    gui.close()
    assert controller.stop_reasons == ["window closed"]
    assert root.after_calls and not root.destroyed


def test_close_destroys_after_background_finishes(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, root, controller = runtime
    controller.running = True
    gui.close()
    controller.running = False
    gui._poll_close()
    assert root.destroyed


def test_close_timeout_terminates_then_kills_and_waits_for_exit(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, root, controller = runtime
    controller.running = True
    gui.close()
    assert gui.close_started_at is not None
    gui.clock = lambda: gui.close_started_at + 36.0  # type: ignore[assignment]
    gui._poll_close()
    assert gui.exit_code == 2
    assert "timed out" in gui.state.latest_error
    assert controller.terminated == 1
    assert controller.killed == 0
    assert not root.destroyed
    gui._poll_close()
    assert controller.terminated == 1
    gui.clock = lambda: gui.close_started_at + 40.0  # type: ignore[assignment]
    gui._poll_close()
    gui._poll_close()
    assert controller.killed == 1
    assert not root.destroyed
    controller.running = False
    gui._poll_close()
    assert root.destroyed
    assert controller.disposed == 1


def test_event_consumption_updates_subtitle_and_render_latency(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, _root, controller = runtime
    gui.clock = lambda: 2.0  # type: ignore[assignment]
    controller.events.put(SubtitleEvent(1, "Привет", "你好", 1.0, 0.2, 0.4, 1.5))
    gui._consume_events()
    assert gui.state.entries[0].chinese_text == "你好"
    assert controller.metrics.snapshot().average_render_latency_seconds == 0.5


def test_segment_error_keeps_previous_subtitle(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, _root, controller = runtime
    controller.events.put(SubtitleEvent(1, "Привет", "你好", 1.0, 0.2, 0.4, 1.0))
    controller.events.put(SegmentErrorEvent(2, "translation", "failed", 1.1))
    gui._consume_events()
    assert gui.state.entries[0].chinese_text == "你好"
    assert "Segment 2" in gui.state.latest_error


def test_fatal_and_stopped_events_update_status(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, _root, controller = runtime
    controller.events.put(StoppedEvent("done", 1.0))
    controller.events.put(FatalErrorEvent("fatal", 2.0))
    gui._consume_events()
    assert gui.state.status == "Fatal error"
    assert gui.state.latest_error == "fatal"
    assert gui.exit_code == 2


def test_controller_source_has_no_tk_calls_and_no_user_path() -> None:
    source = Path(app.__file__).with_name("controller.py").read_text(encoding="utf-8").lower()
    assert "root.after" not in source
    assert ".config(" not in source
    assert "tkinter" not in source
    assert "c:\\users\\" not in source


def test_cli_uses_process_isolation() -> None:
    source = Path(app.__file__).read_text(encoding="utf-8")
    assert "LiveProcessOverlayController(" in source
    assert "write_text(" not in source
    assert "open(" not in source


def test_tk_callback_exception_is_visible_and_requests_safe_stop(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    gui, _root, controller = runtime
    monkeypatch.setattr(diagnostic_logging, "log_directory", lambda: tmp_path)
    monkeypatch.setattr(sys, "stderr", diagnostic_logging.NullTextStream())
    logger = diagnostic_logging.configure_diagnostic_logging()
    try:
        try:
            raise RuntimeError("synthetic callback failure")
        except RuntimeError as exc:
            gui._handle_tk_callback_exception(type(exc), exc, exc.__traceback__)
        content = (tmp_path / "application.log").read_text(encoding="utf-8")
    finally:
        for handler in tuple(logger.handlers):
            if getattr(handler, "_ru_zh_handler", False):
                handler.close()
                logger.removeHandler(handler)
    assert gui.exit_code == 2
    assert gui.state.status == "Fatal error"
    assert "synthetic callback failure" in gui.state.latest_error
    assert controller.stop_reasons == ["GUI callback error"]
    assert "Traceback" in content
    assert "RuntimeError: synthetic callback failure" in content


def test_runtime_installs_tk_callback_exception_handler(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
) -> None:
    gui, root, _controller = runtime
    assert root.report_callback_exception == gui._handle_tk_callback_exception


def test_dead_worker_restores_primary_button_and_allows_restart(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
) -> None:
    from live_subtitles.gui.overlay import SubtitleOverlay

    gui, _root, controller = runtime
    gui.start()
    controller.running = False
    controller.pending_events.append(FatalErrorEvent("Worker died; exitcode=23", 1.0))
    gui.poll()
    assert gui.state.status == "Fatal error"
    assert not gui.overlay.running
    # Exercise the actual button dispatcher, not a direct runtime.start call.
    SubtitleOverlay._start_stop(gui.overlay)
    assert controller.started == 2
    assert gui.state.preparing
    assert not gui.state.latest_error


def test_fatal_error_survives_tail_subtitles_and_normal_stop_events(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
) -> None:
    gui, _root, controller = runtime
    controller.events.put(FatalErrorEvent("engine failure", 1.0))
    controller.events.put(SubtitleEvent(1, "Привет", "你好", 1.0, 0.2, 0.4, 1.1))
    controller.events.put(StoppedEvent("cleanup finished", 1.2))
    gui._consume_events()
    assert gui.state.latest_error == "engine failure"
    assert gui.state.status == "Fatal error"
    assert gui.state.entries[0].chinese_text == "你好"


def test_normal_stop_keeps_controls_stopping_until_worker_really_exits(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
) -> None:
    gui, _root, controller = runtime
    gui.start()
    controller.events.put(StoppedEvent("done", 1.0))
    gui.poll()
    assert gui.state.stopping
    assert gui.overlay.running
    assert not gui.can_change_microphone()
    controller.running = False
    controller.pending_events.append(StoppedEvent("worker exited", 1.1))
    gui.poll()
    assert gui.state.status == "Stopped"
    assert not gui.overlay.running
    assert gui.can_change_microphone()


def test_poll_render_failure_preserves_one_timer_and_consumes_later_stop(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui, root, controller = runtime
    gui.start()
    render = gui.overlay.render

    def fail_render() -> None:
        raise RuntimeError("render failed")

    monkeypatch.setattr(gui.overlay, "render", fail_render)
    try:
        gui.poll()
    except RuntimeError as exc:
        gui._handle_tk_callback_exception(type(exc), exc, exc.__traceback__)
    assert len(root.after_calls) == 1
    assert root.after_calls[0][1] == gui.poll
    assert controller.stop_reasons == ["GUI callback error"]
    monkeypatch.setattr(gui.overlay, "render", render)
    controller.running = False
    controller.pending_events.append(StoppedEvent("cleanup", 2.0))
    root.after_calls.pop()[1]()
    assert not gui.overlay.running
    assert len(root.after_calls) == 1
    assert gui.state.latest_error == "GUI error: RuntimeError: render failed"


def test_close_waits_for_receiver_tail_and_logs_failure_before_destroy(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
) -> None:
    gui, root, controller = runtime
    gui.start()
    gui.close()
    controller.running = False
    controller.tail_pending = True
    gui._poll_close()
    assert not root.destroyed
    assert controller.disposed == 0
    controller.tail_pending = False
    controller.pending_events.append(FatalErrorEvent("worker exitcode=17", 2.0))
    gui._poll_close()
    assert root.destroyed
    assert gui.exit_code == 2
    assert "exitcode=17" in gui.state.latest_error
    assert controller.disposed == 1


def test_close_render_failure_still_requests_stop_and_schedules_cleanup(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui, root, controller = runtime
    gui.start()

    def fail_render() -> None:
        raise RuntimeError("render failure during close")

    monkeypatch.setattr(gui.overlay, "render", fail_render)
    with pytest.raises(RuntimeError):
        gui.close()
    assert controller.stop_reasons == ["window closed"]
    assert root.after_calls[-1][1] == gui._poll_close
    gui.clock = lambda: gui.close_started_at + 36.0
    with pytest.raises(RuntimeError):
        gui._poll_close()
    assert controller.terminated == 1
    assert root.after_calls[-1][1] == gui._poll_close
    assert not root.destroyed


def test_failed_process_start_keeps_error_visible_and_can_retry(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui, _root, controller = runtime
    start = controller.start

    def fail_start() -> bool:
        raise OSError("could not spawn")

    monkeypatch.setattr(controller, "start", fail_start)
    gui.start()
    assert gui.state.status == "Fatal error"
    assert not gui.overlay.running
    assert "could not spawn" in gui.state.latest_error
    monkeypatch.setattr(controller, "start", start)
    gui.start()
    assert gui.state.preparing
    assert not gui.state.latest_error


def test_retry_preflight_error_is_not_overwritten_by_previous_fatal(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
) -> None:
    gui, _root, _controller = runtime
    gui._consume_event(FatalErrorEvent("old engine failure", 1.0))

    def unavailable(_index: int | None) -> AudioDevice:
        raise AudioDeviceError("device disconnected")

    gui.microphone_selector = MicrophoneSelectorModel(99, resolve_device=unavailable)
    gui.start()
    gui.poll()
    assert gui.state.status == "Ready"
    assert "device disconnected" in gui.state.latest_error
    assert "old engine failure" not in gui.state.latest_error


@pytest.mark.parametrize("command", ["live-overlay", "overlay-demo"])
def test_secondary_gui_launch_exits_before_constructing_controller(
    command: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from live_subtitles.gui import single_instance

    calls: list[str] = []

    def duplicate(*, name):
        calls.append(name)
        return SimpleNamespace(primary=False, close=lambda: calls.append("close"))

    def fail_controller(*args, **kwargs):
        pytest.fail("A second launcher must not construct a controller or open a window")

    monkeypatch.setattr(single_instance, "acquire_instance", duplicate)
    monkeypatch.setattr(app, "LiveProcessOverlayController", fail_controller)
    monkeypatch.setattr(app, "DemoOverlayController", fail_controller)
    assert main([command]) == 0
    assert calls == [command, "close"]


def test_primary_lease_released_when_gui_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from live_subtitles import cli
    from live_subtitles.gui import single_instance

    released: list[bool] = []
    lease = SimpleNamespace(primary=True, close=lambda: released.append(True))
    monkeypatch.setattr(single_instance, "acquire_instance", lambda **_: lease)
    monkeypatch.setattr(cli, "configure_diagnostic_logging", lambda: None)

    def fail_tk(_state, _controller, args):
        assert args.instance_lease is lease
        raise RuntimeError("synthetic Tk startup failure")

    monkeypatch.setattr(app, "_run_tk", fail_tk)
    assert main(["overlay-demo"]) == 1
    assert released == [True]


def test_duplicate_activation_preserves_live_session_and_only_reveals_on_request(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController], monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui, root, controller = runtime
    requests = iter((False, True, False))
    calls: list[str] = []
    gui.instance_lease = SimpleNamespace(
        take_activation=lambda: next(requests),
        begin_close=lambda: calls.append("begin close"),
    )
    monkeypatch.setattr(gui.overlay, "reveal", lambda: calls.append("reveal"), raising=False)
    gui.start()
    controller.events.put(SubtitleEvent(1, "Текст", "字幕", 1.0, None, None, 1.0))
    for _ in range(3):
        gui.poll()
    assert calls == ["reveal"]
    assert controller.started == 1 and controller.running
    assert not controller.stop_reasons and gui.state.entries[0].index == 1
    gui.close()
    assert calls == ["reveal", "begin close"]
    assert not root.destroyed


def test_reveal_failure_leaves_running_engine_and_poll_timer_intact(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController], monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui, root, controller = runtime
    gui.start()
    gui.instance_lease = SimpleNamespace(take_activation=lambda: True)

    def fail_reveal():
        raise OSError("synthetic shell failure")

    monkeypatch.setattr(gui.overlay, "reveal", fail_reveal, raising=False)
    gui.poll()
    assert controller.running and not controller.stop_reasons
    assert gui.exit_code == 0 and root.after_calls[-1][1] == gui.poll


def timed_subtitle(index: int = 1, start: float = 2.125, end: float = 4.5) -> SubtitleEvent:
    return SubtitleEvent(
        index, "Привет\nмир", "你好\r\n世界", end - start, 8.0, 12.0, 9_999.0,
        start_seconds=start, end_seconds=end,
    )


def test_srt_is_saved_incrementally_with_audio_timing_even_when_russian_is_hidden(runtime) -> None:
    gui, _root, controller = runtime
    gui.start()
    gui.state.show_russian = False
    path = Path(gui.state.srt_path)
    controller.events.put(timed_subtitle())
    controller.events.put(timed_subtitle())
    gui.poll()
    assert controller.running
    assert path.read_text(encoding="utf-8") == (
        "1\n00:00:02,125 --> 00:00:04,500\nПривет мир\n你好 世界\n\n"
    )
    assert not gui.state.srt_error


def test_clear_and_stop_preserve_srt_and_shutdown_saves_tail_before_destroy(runtime) -> None:
    gui, root, controller = runtime
    gui.start()
    controller.events.put(timed_subtitle())
    gui.poll()
    path = Path(gui.state.srt_path)
    original = path.read_bytes()
    gui.clear()
    assert gui.state.entries == ()
    assert path.read_bytes() == original
    assert gui.state.srt_path == str(path)
    gui.close()
    controller.running = False
    controller.pending_events.extend([
        FatalErrorEvent("worker exitcode=17", 50.0), timed_subtitle(2, 7.0, 8.0),
    ])
    gui._poll_close()
    assert root.destroyed
    assert path.read_bytes().startswith(original)
    assert "2\n00:00:07,000 --> 00:00:08,000" in path.read_text(encoding="utf-8")
    assert gui.state.latest_error == "worker exitcode=17"


def test_restart_creates_new_srt_without_overwriting_previous_session(runtime) -> None:
    gui, _root, controller = runtime
    gui.start()
    controller.events.put(timed_subtitle())
    gui.poll()
    first = Path(gui.state.srt_path)
    original = first.read_bytes()
    controller.running = False
    gui.start()
    second = Path(gui.state.srt_path)
    controller.events.put(timed_subtitle(1, 37.0, 38.0))
    gui.poll()
    assert first != second and first.read_bytes() == original
    assert second.read_text(encoding="utf-8").startswith("1\n00:00:37,000 --> 00:00:38,000\n")


def test_immediate_restart_drains_finished_session_into_its_original_srt(runtime) -> None:
    gui, _root, controller = runtime
    gui.start()
    first = Path(gui.state.srt_path)
    controller.events.put(timed_subtitle())
    controller.running = False
    gui.start()
    second = Path(gui.state.srt_path)
    assert first != second
    assert "00:00:02,125 --> 00:00:04,500" in first.read_text(encoding="utf-8")
    assert second.read_bytes() == b""
    controller.events.put(timed_subtitle(1, 20.0, 21.0))
    gui.poll()
    assert second.read_text(encoding="utf-8").startswith("1\n00:00:20,000 --> 00:00:21,000\n")


def test_restart_drains_more_than_one_gui_tick_of_old_captions(runtime) -> None:
    gui, _root, controller = runtime
    gui.start()
    first = Path(gui.state.srt_path)
    for index in range(1, 201):
        assert controller.events.put(timed_subtitle(index, index * 2, index * 2 + 1))
    controller.running = False
    gui.start()
    assert controller.events.size == 0
    assert len(first.read_text(encoding="utf-8").strip().split("\n\n")) == 200
    assert Path(gui.state.srt_path).read_bytes() == b""


def test_srt_creation_failure_keeps_live_captions_and_latches_warning(runtime, monkeypatch) -> None:
    gui, _root, controller = runtime

    def fail_create(_directory):
        raise PermissionError("synthetic readonly destination")

    monkeypatch.setattr(app.SrtSession, "create", fail_create)
    gui.start()
    controller.events.put(timed_subtitle())
    gui.poll()
    assert controller.running and not controller.stop_reasons
    assert gui.state.entries[0].index == 1
    assert gui.state.srt_error.startswith("SRT saving failed")
    assert gui.state.srt_path == "" and gui.exit_code == 2
    gui.clear()
    assert gui.state.srt_error.startswith("SRT saving failed")


def test_srt_write_failure_keeps_completed_cues_and_retries_only_in_new_session(runtime, monkeypatch) -> None:
    gui, _root, controller = runtime
    gui.start()
    controller.events.put(timed_subtitle())
    gui.poll()
    first = Path(gui.state.srt_path)
    original = first.read_bytes()

    def fail_append(*_args):
        raise OSError("synthetic full disk")

    monkeypatch.setattr(gui._srt_session, "append", fail_append)
    controller.events.put(timed_subtitle(2, 5.0, 6.0))
    gui.poll()
    controller.events.put(timed_subtitle(3, 7.0, 8.0))
    gui.poll()
    assert first.read_bytes() == original
    assert gui.state.entries[-1].index == 3
    assert gui.state.srt_error and controller.running
    controller.running = False
    gui.start()
    assert not gui.state.srt_error and gui.state.srt_path != str(first)
    controller.events.put(timed_subtitle())
    gui.poll()
    assert Path(gui.state.srt_path).read_bytes() == original


def test_missing_audio_timing_is_not_replaced_by_translation_completion(runtime) -> None:
    gui, _root, controller = runtime
    gui.start()
    controller.events.put(SubtitleEvent(1, "Текст", "字幕", 1.0, 5.0, 8.0, 9_999.0))
    gui.poll()
    assert Path(gui.state.srt_path).read_bytes() == b""
    assert gui.state.srt_error and controller.running


def test_open_subtitles_folder_uses_resolved_output_path(runtime, tmp_path, monkeypatch) -> None:
    gui, _root, _controller = runtime
    gui.srt_directory = tmp_path / "custom captions.with.dots"
    gui.start()
    opened = []
    monkeypatch.setattr(app.os, "startfile", opened.append, raising=False)
    gui.open_subtitles_folder()
    assert opened == [str(gui.srt_directory.resolve(strict=True))]
    args = build_parser().parse_args(["live-overlay", "--srt-dir", str(gui.srt_directory)])
    assert args.srt_dir == gui.srt_directory
