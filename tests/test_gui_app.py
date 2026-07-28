from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_subtitles.audio.recording import AudioDevice, AudioDeviceError
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

    def render(self) -> None:
        self.render_count += 1

    def set_running(self, running: bool, *, closing: bool = False) -> None:
        self.running_states.append((running, closing))


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
        ["overlay-demo", "--opacity", "0.4"],
        ["overlay-demo", "--history-lines", "101"],
        ["overlay-demo", "--chinese-font-size", "10"],
        ["overlay-demo", "--russian-font-size", "99"],
        ["overlay-demo", "--ui-poll-ms", "10"],
    ],
)
def test_gui_cli_bounds_are_enforced(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


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


def test_close_timeout_is_explicit(runtime: tuple[app.GuiRuntime, FakeRoot, FakeController]) -> None:
    gui, root, controller = runtime
    controller.running = True
    gui.close()
    assert gui.close_started_at is not None
    gui.clock = lambda: gui.close_started_at + 36.0  # type: ignore[assignment]
    gui._poll_close()
    assert gui.exit_code == 2
    assert "timed out" in gui.state.latest_error
    assert root.after_calls[-1][0] == 250


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


def test_cli_uses_process_isolation_without_persisting_subtitles() -> None:
    source = Path(app.__file__).read_text(encoding="utf-8")
    assert "LiveProcessOverlayController(" in source
    assert "write_text(" not in source
    assert "open(" not in source


def test_tk_callback_exception_is_visible_and_requests_safe_stop(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
    capsys: pytest.CaptureFixture[str],
) -> None:
    gui, _root, controller = runtime
    try:
        raise RuntimeError("synthetic callback failure")
    except RuntimeError as exc:
        gui._handle_tk_callback_exception(type(exc), exc, exc.__traceback__)
    assert gui.exit_code == 2
    assert gui.state.status == "Fatal error"
    assert "synthetic callback failure" in gui.state.latest_error
    assert controller.stop_reasons == ["GUI callback error"]
    stderr = capsys.readouterr().err
    assert "Traceback" in stderr
    assert "RuntimeError: synthetic callback failure" in stderr


def test_runtime_installs_tk_callback_exception_handler(
    runtime: tuple[app.GuiRuntime, FakeRoot, FakeController],
) -> None:
    gui, root, _controller = runtime
    assert root.report_callback_exception == gui._handle_tk_callback_exception
