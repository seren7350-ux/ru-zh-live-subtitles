from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from live_subtitles.gui.overlay import (
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    ModelPanelCallbacks,
    MicrophonePanelCallbacks,
    OverlayRenderer,
    SettingsPanel,
    SubtitleOverlay,
    configure_window_resizing,
    position_coordinates,
    resize_direction_at,
    resized_geometry,
)
from live_subtitles.model_assets import ModelAssetsReport, ModelAssetStatus
from live_subtitles.gui.state import SubtitleEntry, SubtitleViewState
from live_subtitles.gui.microphone_selector import (
    MicrophoneChoice,
    MicrophoneSelectorSnapshot,
)


class FakeWidget:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.options: dict[str, object] = dict(kwargs)
        self.packed = False
        self.pack_options: dict[str, object] = {}
        self.bindings: dict[str, object] = {}
        self.value: object = None
        self.destroyed = False
        self.children: list[FakeWidget] = []
        self.config_calls: list[dict[str, object]] = []
        self.parent = args[0] if args else None
        if isinstance(self.parent, FakeWidget):
            self.parent.children.append(self)

    def config(self, **kwargs: object) -> None:
        self.config_calls.append(dict(kwargs))
        self.options.update(kwargs)

    configure = config

    def cget(self, name: str) -> object:
        return self.options.get(name)

    def pack(self, **kwargs: object) -> None:
        self.packed = True
        self.pack_options = dict(kwargs)

    def pack_propagate(self, value: bool) -> None:
        self.options["pack_propagate"] = value

    def pack_forget(self) -> None:
        self.packed = False

    def bind(self, event: str, callback: object) -> None:
        self.bindings[event] = callback

    def set(self, value: object) -> None:
        self.value = value

    def current(self, value: int | None = None) -> int:
        if value is not None:
            self.value = value
        return int(self.value if self.value is not None else -1)

    def destroy(self) -> None:
        self.destroyed = True

    def after_idle(self, callback: object) -> None:
        callback()

    def after(self, delay: int, callback: object) -> None:
        callback()

    def winfo_width(self) -> int:
        return int(self.options.get("width", 640))

    def winfo_height(self) -> int:
        return int(self.options.get("height", 200))

    def winfo_reqheight(self) -> int:
        return int(self.options.get("reqheight", 100))

    def winfo_y(self) -> int:
        return int(self.options.get("y", 0))

    def winfo_x(self) -> int:
        return int(self.options.get("x", 0))

    def winfo_rootx(self) -> int:
        return self.winfo_x()

    def winfo_rooty(self) -> int:
        return self.winfo_y()

    def update_idletasks(self) -> None:
        return None

    def add(self, child, **kwargs):
        self.children.append(child)

    def yview(self, *args):
        pass

    def create_window(self, *args, **kwargs):
        return 1

    def itemconfigure(self, *args, **kwargs):
        pass

    def bbox(self, *args):
        return (0, 0, 380, 500)


class FakeToplevel(FakeWidget):
    def __init__(self, *_args: object, **kwargs: object) -> None:
        super().__init__(*_args, **kwargs)
        self._exists = True
        self._state = "normal"
        self._geometry = "260x560+20+20"
        self.transient_owner: object | None = None
        self.attribute_calls: list[tuple[str, object]] = []
        self.lift_calls = 0
        self.withdraw_calls = 0
        self.deiconify_calls = 0
        self.destroy_calls = 0
        self.protocols: dict[str, object] = {}

    def title(self, value: str) -> None:
        self.options["title"] = value

    def transient(self, owner: object) -> None:
        self.transient_owner = owner

    def attributes(self, name: str, value: object) -> None:
        self.attribute_calls.append((name, value))

    def protocol(self, name: str, callback: object) -> None:
        self.protocols[name] = callback

    def winfo_exists(self) -> int:
        return int(self._exists)

    def state(self) -> str:
        if not self._exists:
            raise RuntimeError("bad window path name")
        return self._state

    def withdraw(self) -> None:
        if not self._exists:
            raise RuntimeError("bad window path name")
        self.withdraw_calls += 1
        self._state = "withdrawn"

    def deiconify(self) -> None:
        if not self._exists:
            raise RuntimeError("bad window path name")
        self.deiconify_calls += 1
        self._state = "normal"

    def geometry(self, value: str | None = None) -> str:
        if value is not None:
            self._geometry = value
        return self._geometry

    def lift(self) -> None:
        self.lift_calls += 1

    def minsize(self, width, height):
        self.options['minsize'] = (width, height)

    def destroy(self) -> None:
        self.destroy_calls += 1
        self._exists = False


class FakeTk:
    TclError = RuntimeError

    def __init__(self) -> None:
        self.toplevels: list[FakeToplevel] = []

    def Toplevel(self, *_args: object, **kwargs: object) -> FakeToplevel:  # noqa: N802
        window = FakeToplevel(**kwargs)
        self.toplevels.append(window)
        return window

    Frame = FakeWidget
    Button = FakeWidget
    Label = FakeWidget
    Scale = FakeWidget
    Canvas = FakeWidget
    Checkbutton = FakeWidget

    class BooleanVar:
        def __init__(self, master=None, value=False):
            self.value = value

        def set(self, value):
            self.value = value

        def get(self):
            return self.value


class FakeTtk:
    Combobox = FakeWidget
    Notebook = FakeWidget
    Scrollbar = FakeWidget


class FakeRoot(FakeWidget):
    def __init__(self) -> None:
        super().__init__()
        self.attribute_calls: list[tuple[str, object]] = []
        self.override_calls: list[bool] = []
        self.geometry_calls: list[str] = []
        self._geometry = "800x280+100+620"
        self.after_idle_callbacks: list[object] = []
        self.protocols: dict[str, object] = {}
        self.destroy_calls = 0
        self.resizable_calls: list[tuple[bool, bool]] = []

    def title(self, value: str) -> None:
        self.options["title"] = value

    def protocol(self, name: str, callback: object) -> None:
        self.protocols[name] = callback

    @staticmethod
    def winfo_screenwidth() -> int:
        return 1200

    @staticmethod
    def winfo_screenheight() -> int:
        return 900

    @staticmethod
    def winfo_width() -> int:
        return 800

    @staticmethod
    def winfo_height() -> int:
        return 280

    @staticmethod
    def winfo_x() -> int:
        return 100

    @staticmethod
    def winfo_y() -> int:
        return 620

    def minsize(self, width: int, height: int) -> None:
        self.options["minsize"] = (width, height)

    def resizable(self, width: bool, height: bool) -> None:
        self.resizable_calls.append((width, height))

    def winfo_rootx(self) -> int:
        return self.winfo_x()

    def winfo_rooty(self) -> int:
        return self.winfo_y()

    def attributes(self, name: str, value: object) -> None:
        self.attribute_calls.append((name, value))

    def overrideredirect(self, value: bool) -> None:
        self.override_calls.append(value)

    def geometry(self, value: str | None = None) -> str:
        if value is not None:
            self._geometry = value
            self.geometry_calls.append(value)
        return self._geometry

    def after_idle(self, callback: object) -> None:
        self.after_idle_callbacks.append(callback)

    def run_idle(self) -> None:
        callbacks, self.after_idle_callbacks = self.after_idle_callbacks, []
        for callback in callbacks:
            callback()

    def destroy(self) -> None:
        self.destroy_calls += 1


def build_panel(
    *,
    state: SubtitleViewState | None = None,
    running: bool = False,
    microphone: MicrophonePanelCallbacks | None = None,
    models: ModelPanelCallbacks | None = None,
    on_open_subtitles: Any = None,
) -> tuple[SettingsPanel, FakeRoot, FakeTk, list[str]]:
    view_state = state or SubtitleViewState()
    root = FakeRoot()
    tk = FakeTk()
    calls: list[str] = []
    no_op = lambda *args: None
    panel = SettingsPanel(
        root,
        view_state,
        on_start_stop=lambda: calls.append("start-stop"),
        on_clear=no_op,
        on_toggle_russian=no_op,
        on_toggle_topmost=no_op,
        on_toggle_borderless=no_op,
        on_position=no_op,
        on_opacity=no_op,
        on_chinese_font=no_op,
        on_russian_font=no_op,
        on_exit=no_op,
        is_running=lambda: running,
        microphone=microphone,
        models=models,
        on_open_subtitles=on_open_subtitles,
        tk_module=tk,
        ttk_module=FakeTtk,
    )
    return panel, root, tk, calls


def microphone_callbacks(
    *, can_change: bool = True
) -> tuple[MicrophonePanelCallbacks, list[str], dict[str, MicrophoneSelectorSnapshot]]:
    snapshot = MicrophoneSelectorSnapshot(
        choices=(
            MicrophoneChoice(None, "System default"),
            MicrophoneChoice(1, "1 — Input (1 channel, 48000 Hz) [default]"),
        ),
        selected_index=None,
        selected_position=0,
        status="Selected for next session: System default",
    )
    holder = {"snapshot": snapshot}
    calls: list[str] = []

    def refresh() -> MicrophoneSelectorSnapshot:
        calls.append("refresh")
        return holder["snapshot"]

    def select(index: int | None) -> MicrophoneSelectorSnapshot:
        calls.append(f"select:{index}")
        holder["snapshot"] = MicrophoneSelectorSnapshot(
            choices=snapshot.choices,
            selected_index=index,
            selected_position=0 if index is None else 1,
            status=f"Selected for next session: {index}",
        )
        return holder["snapshot"]

    return (
        MicrophonePanelCallbacks(
            refresh=refresh,
            select=select,
            snapshot=lambda: holder["snapshot"],
            can_change=lambda: can_change,
        ),
        calls,
        holder,
    )


def model_callbacks(tmp_path: Path, *, ready: bool) -> tuple[ModelPanelCallbacks, list[str]]:
    status = ModelAssetStatus(
        key="nllb",
        model_id="facebook/nllb-200-distilled-600M",
        revision="f" * 40,
        ready=ready,
        location=tmp_path / "snapshot",
        cache_root=tmp_path / "hub",
        missing_files=() if ready else ("pytorch_model.bin",),
    )
    report = ModelAssetsReport(tmp_path / "models", tmp_path / "hub", (status,))
    calls: list[str] = []
    callbacks = ModelPanelCallbacks(
        recheck=lambda: calls.append("recheck") or report,
        snapshot=lambda: report,
        open_folder=lambda: calls.append("folder"),
        open_instructions=lambda: calls.append("instructions"),
    )
    return callbacks, calls


def test_renderer_updates_bilingual_text_without_window_manager_calls() -> None:
    root = FakeRoot()
    widgets = [FakeWidget() for _ in range(4)]
    renderer = OverlayRenderer(
        root,
        status_widget=widgets[0],
        russian_widget=widgets[1],
        chinese_widget=widgets[2],
        error_widget=widgets[3],
    )
    state = SubtitleViewState(show_russian=True)
    state.add_subtitle(SubtitleEntry(1, "Привет", "你好", 0.0, 0.1, 0.2))
    renderer.render(state)
    assert widgets[1].options["text"] == "Привет"
    assert widgets[2].options["text"] == "你好"
    assert root.attribute_calls == []
    assert root.override_calls == []


def test_show_russian_false_hides_only_russian_text() -> None:
    root = FakeRoot()
    widgets = [FakeWidget() for _ in range(4)]
    renderer = OverlayRenderer(
        root,
        status_widget=widgets[0],
        russian_widget=widgets[1],
        chinese_widget=widgets[2],
        error_widget=widgets[3],
    )
    state = SubtitleViewState(show_russian=False)
    state.add_subtitle(SubtitleEntry(1, "Привет", "你好", 0.0, 0.1, 0.2))
    renderer.render(state)
    assert widgets[1].options["text"] == ""
    assert widgets[2].options["text"] == "你好"


def test_renderer_displays_only_latest_caption_and_normalizes_line_breaks() -> None:
    root = FakeRoot()
    widgets = [FakeWidget() for _ in range(4)]
    renderer = OverlayRenderer(
        root, status_widget=widgets[0], russian_widget=widgets[1],
        chinese_widget=widgets[2], error_widget=widgets[3],
    )
    state = SubtitleViewState(history_lines=5)
    state.add_subtitle(SubtitleEntry(1, "Previous Russian", "上一条中文", 0.0, 0.1, 0.2))
    state.add_subtitle(SubtitleEntry(2, "Русский\r\nтекст", "中文\n字幕", 0.0, 0.1, 0.2))
    renderer.render(state)
    assert widgets[1].options["text"] == "Русский текст"
    assert widgets[2].options["text"] == "中文 字幕"


def test_new_caption_keeps_srt_warning_visible() -> None:
    widgets = [FakeWidget() for _ in range(4)]
    renderer = OverlayRenderer(
        FakeRoot(), status_widget=widgets[0], russian_widget=widgets[1],
        chinese_widget=widgets[2], error_widget=widgets[3],
    )
    state = SubtitleViewState()
    state.srt_error = "Unable to save subtitles."
    state.add_subtitle(SubtitleEntry(1, "Привет", "你好", 0.0, 0.1, 0.2))
    renderer.render(state)
    assert widgets[3].options["text"] == state.srt_error
    state.latest_error = "Fatal engine error."
    renderer.render(state)
    assert widgets[3].options["text"] == state.latest_error


def test_settings_exposes_srt_destination_and_keeps_save_failure() -> None:
    state = SubtitleViewState()
    opened = []
    panel, _, _, _ = build_panel(
        state=state, on_open_subtitles=lambda: opened.append(True),
    )
    assert "next session" in panel.subtitles_status.options["text"]
    state.srt_path = str(Path("saved-subtitles") / "lecture.srt")
    panel.sync()
    assert "saved automatically" in panel.subtitles_status.options["text"]
    panel.subtitles_button.options["command"]()
    assert opened == [True]
    state.srt_error = "Cannot write subtitles."
    panel.sync()
    assert panel.subtitles_status.options["text"] == state.srt_error
    assert panel.subtitles_status.options["foreground"] == "#ff8a80"


def test_drag_uses_initial_pointer_offset() -> None:
    root = FakeRoot()
    widgets = [FakeWidget() for _ in range(4)]
    renderer = OverlayRenderer(
        root,
        status_widget=widgets[0],
        russian_widget=widgets[1],
        chinese_widget=widgets[2],
        error_widget=widgets[3],
    )
    renderer.begin_drag(SimpleNamespace(x_root=125, y_root=650))
    renderer.drag(SimpleNamespace(x_root=300, y_root=450))
    assert root.geometry_calls[-1] == "+275+420"


def test_root_enables_native_decorated_resize_with_minimum_size() -> None:
    root = FakeRoot()
    configure_window_resizing(root)
    assert root.options["minsize"] == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert root.resizable_calls == [(True, True)]


@pytest.mark.parametrize(
    ("point", "direction"),
    [
        ((1, 100), "w"),
        ((799, 100), "e"),
        ((400, 1), "n"),
        ((400, 279), "s"),
        ((1, 1), "nw"),
        ((799, 1), "ne"),
        ((1, 279), "sw"),
        ((799, 279), "se"),
        ((400, 140), None),
    ],
)
def test_borderless_resize_hit_area_covers_edges_and_corners(
    point: tuple[int, int], direction: str | None
) -> None:
    assert resize_direction_at(*point, width=800, height=280) == direction


@pytest.mark.parametrize("direction", sorted(("n", "s", "e", "w", "ne", "nw", "se", "sw")))
def test_resize_geometry_supports_all_eight_directions(direction: str) -> None:
    x, y, width, height = resized_geometry(
        x=100,
        y=200,
        width=800,
        height=400,
        direction=direction,
        delta_x=40,
        delta_y=30,
    )
    assert width == (760 if "w" in direction else 840 if "e" in direction else 800)
    assert height == (370 if "n" in direction else 430 if "s" in direction else 400)
    assert x == (140 if "w" in direction else 100)
    assert y == (230 if "n" in direction else 200)


def test_resize_geometry_clamps_minimum_and_moves_only_left_top_edges() -> None:
    assert resized_geometry(
        x=100,
        y=200,
        width=800,
        height=400,
        direction="nw",
        delta_x=700,
        delta_y=350,
    ) == (380, 420, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert resized_geometry(
        x=100,
        y=200,
        width=800,
        height=400,
        direction="se",
        delta_x=-700,
        delta_y=-350,
    ) == (100, 200, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


@pytest.mark.parametrize(
    ("preset", "expected"),
    [("top", (200, 20)), ("bottom", (200, 630)), ("floating", (123, 456))],
)
def test_position_presets(preset: str, expected: tuple[int, int]) -> None:
    assert position_coordinates(
        screen_width=1200,
        screen_height=900,
        window_width=800,
        window_height=200,
        preset=preset,
        current_x=123,
        current_y=456,
    ) == expected


def test_settings_panel_is_persistent_and_close_withdraws() -> None:
    panel, _root, tk, _calls = build_panel()
    panel.show()
    panel.hide()
    panel.show()
    assert len(tk.toplevels) == 1
    assert panel.window.withdraw_calls == 1
    assert panel.window.destroy_calls == 0
    assert panel.window.deiconify_calls == 2
    assert panel.window.lift_calls == 2


def test_settings_rechecks_position_after_async_saved_geometry(monkeypatch) -> None:
    from live_subtitles.gui import workarea
    monkeypatch.setattr(workarea, "work_area", lambda *_args: (0, 0, 1920, 1040))
    panel, _root, _tk, _calls = build_panel()
    delayed = []
    panel.window.after = lambda delay, callback: delayed.append(callback)
    panel.window.options.update(x=50, y=100, width=440, height=560)
    panel.show()  # idle sees the old in-bounds geometry
    panel.window.options['y'] = 950  # WM applies the saved position later
    delayed.pop()()
    assert panel.window.geometry() == '440x560+50+480'
    panel.hide()
    panel.window.options['y'] = 950
    panel._fit_into_workarea()  # a late callback must not remap a hidden dialog
    assert panel.window.state() == 'withdrawn'


def test_f8_starts_or_stops_from_settings_and_stops_event_propagation() -> None:
    panel, _root, _tk, calls = build_panel()
    assert panel.window.bindings['<F8>'](None) == 'break'
    assert calls == ['start-stop']
    overlay, root = overlay_stub()
    overlay._start_stop = Mock()
    assert overlay._start_stop_key(None) == 'break'
    overlay._start_stop.assert_called_once_with()


def test_settings_panel_inherits_topmost_when_shown_without_polling_wm_state() -> None:
    state = SubtitleViewState(topmost=True)
    panel, _root, _tk, _calls = build_panel(state=state)
    panel.show()
    assert panel.window.attribute_calls[-1] == ("-topmost", True)
    calls_after_show = list(panel.window.attribute_calls)
    state.topmost = False
    panel.sync()
    assert panel.window.attribute_calls == calls_after_show
    panel.hide()
    panel.show()
    assert panel.window.attribute_calls[-1] == ("-topmost", False)


def test_live_settings_has_readonly_microphone_selector_and_refreshes_once() -> None:
    callbacks, calls, _holder = microphone_callbacks()
    panel, _root, _tk, _calls = build_panel(microphone=callbacks)
    assert panel.microphone_combobox is not None
    assert panel.microphone_combobox.options["state"] == "readonly"
    assert panel.microphone_refresh_button is not None
    assert calls == ["refresh"]
    panel.show()
    panel.sync()
    assert calls == ["refresh"]


def test_overlay_demo_settings_omits_microphone_region() -> None:
    panel, _root, _tk, _calls = build_panel(microphone=None)
    assert panel.microphone_combobox is None
    assert panel.microphone_refresh_button is None
    assert panel.microphone_status is None


def test_live_settings_shows_model_assets_without_polling(tmp_path: Path) -> None:
    callbacks, calls = model_callbacks(tmp_path, ready=False)
    panel, _root, _tk, _calls = build_panel(models=callbacks)
    assert panel.model_status is not None
    assert "Model setup required" in str(panel.model_status.options["text"])
    panel.sync()
    assert calls == []
    assert panel.model_recheck_button is not None
    command = panel.model_recheck_button.options["command"]
    assert callable(command)
    command()
    assert calls == ["recheck"]


def test_demo_settings_omits_model_assets(tmp_path: Path) -> None:
    panel, _root, _tk, _calls = build_panel(models=None)
    assert panel.model_status is None
    assert panel.model_recheck_button is None


def test_microphone_combobox_maps_position_to_index_without_parsing_label() -> None:
    callbacks, calls, _holder = microphone_callbacks()
    panel, _root, _tk, _calls = build_panel(microphone=callbacks)
    assert panel.microphone_combobox is not None
    panel.microphone_combobox.current(1)
    panel._on_microphone_selected()
    assert calls == ["refresh", "select:1"]


@pytest.mark.parametrize(
    ("status", "running"),
    [
        ("Preparing...", False),
        ("Stopping...", False),
        ("Listening...", True),
    ],
)
def test_microphone_controls_are_disabled_until_fully_stopped(
    status: str, running: bool
) -> None:
    state = SubtitleViewState()
    state.set_status(status)
    callbacks, _calls, _holder = microphone_callbacks()
    panel, _root, _tk, _panel_calls = build_panel(
        state=state,
        running=running,
        microphone=callbacks,
    )
    assert panel.microphone_combobox is not None
    assert panel.microphone_refresh_button is not None
    assert panel.microphone_status is not None
    assert panel.microphone_combobox.options["state"] == "disabled"
    assert panel.microphone_refresh_button.options["state"] == "disabled"
    assert panel.microphone_status.options["text"] == (
        "Stop subtitles before changing the microphone."
    )


def test_microphone_controls_enable_when_stopped() -> None:
    callbacks, _calls, _holder = microphone_callbacks()
    panel, _root, _tk, _panel_calls = build_panel(microphone=callbacks)
    assert panel.microphone_combobox is not None
    assert panel.microphone_refresh_button is not None
    assert panel.microphone_combobox.options["state"] == "readonly"
    assert panel.microphone_refresh_button.options["state"] == "normal"


def test_refresh_button_reenumerates_without_starting_or_stopping() -> None:
    callbacks, calls, _holder = microphone_callbacks()
    panel, _root, _tk, panel_calls = build_panel(microphone=callbacks)
    assert panel.microphone_refresh_button is not None
    command = panel.microphone_refresh_button.options["command"]
    assert callable(command)
    command()
    assert calls == ["refresh", "refresh"]
    assert panel_calls == []


def overlay_stub() -> tuple[SubtitleOverlay, FakeRoot]:
    overlay = SubtitleOverlay.__new__(SubtitleOverlay)
    overlay.tk = FakeTk()
    overlay.root = FakeRoot()
    overlay.state = SubtitleViewState(borderless=True)
    overlay.on_start = lambda: None
    overlay.on_stop = lambda: None
    overlay.on_clear = lambda: None
    overlay.on_exit = lambda: None
    overlay.on_open_subtitles = None
    overlay.running = False
    overlay.closing = False
    overlay.settings_panel = None
    overlay._taskbar = None
    overlay._borderless_transition_pending = False
    overlay._dragging = False
    overlay._drag_origin = None
    overlay._drag_moved = False
    overlay._resize_session = None
    overlay._toolbar_packed = True
    overlay.control_bar = FakeWidget()
    overlay.control_bar.pack(fill="x", side="bottom")
    overlay.content = FakeWidget()
    overlay._window_width = 800
    overlay._window_height = 280
    overlay._minimum_window_height = MIN_WINDOW_HEIGHT
    overlay._last_root_size = (800, 280)
    overlay.renderer = OverlayRenderer(
        overlay.root,
        status_widget=FakeWidget(),
        russian_widget=FakeWidget(),
        chinese_widget=FakeWidget(),
        error_widget=FakeWidget(),
    )
    overlay.render = lambda: None
    return overlay, overlay.root


def test_taskbar_sync_only_follows_main_window_map_while_open() -> None:
    overlay, root = overlay_stub()
    taskbar = Mock()
    overlay._taskbar = taskbar
    overlay._on_root_map(SimpleNamespace(widget=FakeWidget()))
    assert root.after_idle_callbacks == []
    overlay._on_root_map(SimpleNamespace(widget=root))
    root.run_idle()
    taskbar.ensure_button.assert_called_once_with(root)
    overlay._on_root_map(SimpleNamespace(widget=root))
    overlay.closing = True
    root.run_idle()
    overlay._on_root_map(SimpleNamespace(widget=root))
    assert root.after_idle_callbacks == []
    taskbar.ensure_button.assert_called_once_with(root)


def test_render_and_session_status_changes_do_not_touch_taskbar() -> None:
    overlay, root = overlay_stub()
    del overlay.render
    overlay.control_bar = FakeWidget()
    overlay.content = FakeWidget()
    overlay.pin_button = FakeWidget()
    overlay.start_stop_button = FakeWidget()
    overlay._taskbar = Mock()
    overlay.set_running(True)
    overlay.state.add_subtitle(SubtitleEntry(1, "Привет", "你好", 0.0, 0.1, 0.2))
    overlay.render()
    overlay.set_running(False)
    assert overlay._taskbar.method_calls == []
    assert not (root.attribute_calls or root.override_calls or root.geometry_calls)


def test_borderless_resize_does_not_trigger_drag_and_sets_floating() -> None:
    overlay, root = overlay_stub()
    start = SimpleNamespace(x_root=101, y_root=700)
    overlay._begin_drag(start)
    assert not overlay._dragging
    overlay._begin_resize(start)
    assert overlay._resize_session is not None
    overlay._resize_drag(SimpleNamespace(x_root=141, y_root=700))
    assert root.geometry_calls[-1] == "760x280+140+620"
    assert overlay.state.position == "floating"


def test_small_window_minimum_includes_complete_subtitle_rows() -> None:
    overlay, root = overlay_stub()
    overlay.subtitle_view = SimpleNamespace(canvas=FakeWidget(height=30))
    overlay._set_subtitle_minimum_height(70)
    assert root.options["minsize"] == (MIN_WINDOW_WIDTH, 320)
    overlay._begin_resize(SimpleNamespace(x_root=400, y_root=899))
    overlay._resize_drag(SimpleNamespace(x_root=400, y_root=800))
    assert root.geometry_calls[-1].startswith("800x320")


def test_drag_area_does_not_trigger_resize() -> None:
    overlay, root = overlay_stub()
    start = SimpleNamespace(x_root=300, y_root=700)
    overlay._begin_resize(start)
    assert overlay._resize_session is None
    overlay._begin_drag(start)
    overlay._drag(SimpleNamespace(x_root=420, y_root=760))
    assert root.geometry_calls[-1] == "+220+680"


def test_decorated_mode_disables_custom_resize_cursor_and_geometry() -> None:
    overlay, root = overlay_stub()
    overlay.state.borderless = False
    edge = SimpleNamespace(x_root=101, y_root=700)
    overlay._update_resize_cursor(edge)
    overlay._begin_resize(edge)
    assert root.options["cursor"] == ""
    assert overlay._resize_session is None
    assert root.geometry_calls == []


def test_resize_callback_error_does_not_change_session_shutdown_state() -> None:
    overlay, root = overlay_stub()
    overlay.running = True
    overlay.closing = False
    edge = SimpleNamespace(x_root=101, y_root=700)
    overlay._begin_resize(edge)

    def fail_geometry(_value: str | None = None) -> str:
        raise RuntimeError("window disappeared")

    root.geometry = fail_geometry  # type: ignore[method-assign]
    overlay._resize_drag(SimpleNamespace(x_root=141, y_root=700))
    assert overlay._resize_session is None
    assert overlay.running
    assert not overlay.closing


class FakePanel:
    def __init__(self, state: SubtitleViewState) -> None:
        self.state_model = state
        self.window = FakeToplevel()
        self.show_calls = 0
        self.hide_calls = 0

    def exists(self) -> bool:
        return bool(self.window._exists)

    def is_visible(self) -> bool:
        return self.exists() and self.window._state != "withdrawn"

    def show(self) -> None:
        self.show_calls += 1
        self.window.deiconify()
        self.state_model.settings_visible = True

    def hide(self) -> None:
        self.hide_calls += 1
        if self.exists():
            self.window.withdraw()
        self.state_model.settings_visible = False

    def sync(self) -> None:
        pass


def test_settings_toggle_only_changes_panel_visibility_and_reuses_instance() -> None:
    overlay, _root = overlay_stub()
    created: list[FakePanel] = []

    def create() -> FakePanel:
        panel = FakePanel(overlay.state)
        overlay.settings_panel = panel  # type: ignore[assignment]
        created.append(panel)
        return panel

    overlay._create_settings_panel = create  # type: ignore[method-assign]
    original_values = (overlay.state.borderless, overlay.state.topmost, overlay.running)
    overlay.toggle_settings_panel()
    panel = created[0]
    overlay.toggle_settings_panel()
    overlay.toggle_settings_panel()
    assert len(created) == 1
    assert panel.hide_calls == 1
    assert panel.show_calls == 2
    assert (overlay.state.borderless, overlay.state.topmost, overlay.running) == original_values


def test_destroyed_settings_panel_is_safely_recreated() -> None:
    overlay, _root = overlay_stub()
    first = FakePanel(overlay.state)
    first.window.destroy()
    overlay.settings_panel = first  # type: ignore[assignment]
    created: list[FakePanel] = []

    def create() -> FakePanel:
        panel = FakePanel(overlay.state)
        overlay.settings_panel = panel  # type: ignore[assignment]
        created.append(panel)
        return panel

    overlay._create_settings_panel = create  # type: ignore[method-assign]
    overlay.toggle_settings_panel()
    assert len(created) == 1
    assert overlay.settings_panel is created[0]


def test_right_click_uses_same_settings_toggle() -> None:
    overlay, _root = overlay_stub()
    calls: list[str] = []
    overlay.toggle_settings_panel = lambda: calls.append("toggle")  # type: ignore[method-assign]
    overlay._on_context_request(SimpleNamespace())
    assert calls == ["toggle"]


def test_right_click_bindings_are_single_release_bindings() -> None:
    source = Path(__file__).parents[1].joinpath(
        "src/live_subtitles/gui/overlay.py"
    ).read_text(encoding="utf-8")
    assert source.count('bind("<ButtonRelease-3>", self._on_context_request)') == 1
    assert 'bind("<Button-3>"' not in source
    assert "add=\"+\"" not in source


def test_borderless_toggle_withdraws_panel_then_restores_window_state_idle() -> None:
    overlay, root = overlay_stub()
    panel = FakePanel(overlay.state)
    overlay.settings_panel = panel  # type: ignore[assignment]
    original_geometry = root.geometry()
    overlay.toggle_borderless()
    assert panel.hide_calls == 1
    assert not overlay.state.settings_visible
    assert root.override_calls == [False]
    assert root.after_idle_callbacks
    assert root.destroy_calls == 0
    root.run_idle()
    assert root.geometry() == original_geometry
    assert root.attribute_calls[-2:] == [("-topmost", True), ("-alpha", 0.88)]
    assert not overlay._borderless_transition_pending


def test_ten_borderless_round_trips_do_not_rebuild_or_accumulate() -> None:
    overlay, root = overlay_stub()
    panel = FakePanel(overlay.state)
    overlay.settings_panel = panel  # type: ignore[assignment]
    session_identity = object()
    overlay.session_identity = session_identity
    for _ in range(10):
        overlay.toggle_borderless()
        root.run_idle()
    assert len(root.override_calls) == 10
    assert root.destroy_calls == 0
    assert overlay.settings_panel is panel
    assert overlay.session_identity is session_identity


def test_direct_primary_button_stops_without_settings_or_right_click() -> None:
    overlay, _root = overlay_stub()
    calls: list[str] = []
    overlay.running = True
    overlay.on_stop = lambda: calls.append("stop")
    overlay._start_stop()
    assert calls == ["stop"]
    assert overlay.settings_panel is None


def test_topmost_toggle_does_not_start_session_or_rebuild_window() -> None:
    overlay, root = overlay_stub()
    start_calls: list[str] = []
    overlay.on_start = lambda: start_calls.append("start")
    panel = FakePanel(overlay.state)
    overlay.settings_panel = panel  # type: ignore[assignment]
    overlay.toggle_topmost()
    overlay.toggle_topmost()
    assert start_calls == []
    assert root.attribute_calls[-2:] == [("-topmost", False), ("-topmost", True)]
    assert root.destroy_calls == 0


def test_source_has_fixed_settings_label_no_layout_modes_or_focus_grab() -> None:
    source = Path(__file__).parents[1].joinpath(
        "src/live_subtitles/gui/overlay.py"
    ).read_text(encoding="utf-8")
    state_source = Path(__file__).parents[1].joinpath(
        "src/live_subtitles/gui/state.py"
    ).read_text(encoding="utf-8")
    assert 'self._control_button("Settings"' in source
    assert "Compact" not in source
    assert "Expanded" not in source
    assert "captions_only" not in source
    assert "control_mode" not in state_source
    assert "focus_force" not in source
    assert "grab_set" not in source
    assert "tk.Menu" not in source
    assert "threading" not in source


def pointer(x: int, y: int, widget_class: str = "Canvas") -> SimpleNamespace:
    return SimpleNamespace(
        x_root=x, y_root=y,
        widget=SimpleNamespace(winfo_class=lambda: widget_class),
    )


@pytest.mark.parametrize("widget_class", ["Canvas", "Frame", "Label"])
def test_drag_from_caption_background_or_label_respects_click_threshold(widget_class) -> None:
    overlay, root = overlay_stub()
    overlay._begin_pointer_action(pointer(300, 700, widget_class))
    overlay._pointer_drag(pointer(302, 701, widget_class))
    assert root.geometry_calls == []
    overlay._pointer_drag(pointer(320, 730, widget_class))
    assert root.geometry_calls == ["+120+650"]
    overlay._end_pointer_action(pointer(320, 730, widget_class))
    overlay._pointer_drag(pointer(500, 750, widget_class))
    assert root.geometry_calls == ["+120+650"]


@pytest.mark.parametrize("widget_class", ["Button", "TButton", "Scale", "TCombobox", "Entry"])
def test_control_clicks_and_doubleclicks_do_not_drag_resize_or_hide_toolbar(widget_class) -> None:
    overlay, root = overlay_stub()
    overlay._begin_pointer_action(pointer(101, 700, widget_class))
    overlay._pointer_drag(pointer(220, 740, widget_class))
    assert overlay._toggle_toolbar_event(pointer(300, 700, widget_class)) is None
    assert not overlay._dragging and overlay._resize_session is None
    assert overlay.state.toolbar_visible and root.geometry_calls == []


def test_field_border_resizes_before_drag_and_ignores_doubleclick() -> None:
    overlay, root = overlay_stub()
    overlay._begin_pointer_action(pointer(101, 700))
    assert overlay._resize_session is not None and not overlay._dragging
    overlay._pointer_drag(pointer(141, 700))
    assert root.geometry_calls[-1] == "760x280+140+620"
    assert overlay._toggle_toolbar_event(pointer(101, 700)) is None
    assert overlay.state.toolbar_visible


def test_doubleclick_hides_and_restores_same_toolbar_without_moving_window() -> None:
    overlay, root = overlay_stub()
    bar = overlay.control_bar
    overlay._begin_pointer_action(pointer(300, 700))
    assert overlay._toggle_toolbar_event(pointer(300, 700)) == "break"
    assert not overlay.state.toolbar_visible and not bar.packed
    assert not overlay._dragging
    overlay._pointer_drag(pointer(400, 750))
    assert root.geometry_calls == []
    overlay._toggle_toolbar_event(pointer(300, 700))
    assert overlay.state.toolbar_visible and bar.packed
    assert overlay.control_bar is bar
    assert bar.pack_options["before"] is overlay.content


def test_reveal_or_focus_recovers_opaque_settings_without_resetting_zero_alpha() -> None:
    overlay, root = overlay_stub()
    overlay.state.opacity = 0.0
    overlay.state.text_opacity = 0.0
    overlay.state.toolbar_visible = False
    panel, _, _, _ = build_panel(state=overlay.state)
    panel.hide()
    overlay.settings_panel = panel
    root.state = lambda: "normal"
    root.lift = lambda: None
    overlay._on_root_focus(SimpleNamespace(widget=root))
    assert panel.is_visible() and ("-alpha", 1.0) in panel.window.attribute_calls
    panel.hide()
    overlay.reveal()
    assert panel.is_visible()
    assert overlay.state.opacity == overlay.state.text_opacity == 0.0
    assert not overlay.state.toolbar_visible


def test_dismissing_settings_does_not_immediately_reopen_on_returned_focus() -> None:
    overlay, root = overlay_stub()
    overlay.state.opacity = 0.0
    panel, _, _, _ = build_panel(state=overlay.state)
    panel._on_hide = overlay._suppress_focus_recovery
    overlay.settings_panel = panel
    panel.show()
    panel.hide()
    overlay._on_root_focus(SimpleNamespace(widget=root))
    assert not panel.is_visible()
    overlay._on_root_focus_out(SimpleNamespace(widget=root))
    overlay._on_root_focus(SimpleNamespace(widget=root))
    assert panel.is_visible()


def test_independent_alpha_controls_cover_zero_and_outline_render() -> None:
    overlay, root = overlay_stub()
    rendered = []
    overlay.render = lambda: rendered.append((overlay.state.text_opacity, overlay.state.text_outline))
    overlay.set_opacity(0.0)
    assert overlay.state.opacity == 0.0 and overlay.state.text_opacity == 1.0
    assert root.attribute_calls == [("-alpha", 0.0)]
    overlay.set_text_opacity(0.0)
    overlay.toggle_text_outline()
    assert overlay.state.opacity == 0.0 and overlay.state.text_opacity == 0.0
    assert rendered == [(0.0, False), (0.0, True)]
    assert root.attribute_calls == [("-alpha", 0.0)]


def test_settings_opacity_sliders_use_full_percent_range_and_toolbar_label() -> None:
    panel, _, _, _ = build_panel(state=SubtitleViewState(opacity=0, text_opacity=0))
    assert panel.opacity_scale.options["from_"] == 0
    assert panel.opacity_scale.options["to"] == 100
    assert panel.text_opacity_scale.options["from_"] == 0
    assert panel.text_opacity_scale.options["to"] == 100
    assert panel.opacity_scale.value == panel.text_opacity_scale.value == 0
    assert panel._checks['toolbar_visible'].get() is True
    panel.state_model.toolbar_visible = False
    panel.sync()
    assert panel._checks['toolbar_visible'].get() is False


def test_caption_surface_follows_moves_maps_and_borderless_owner_transition() -> None:
    overlay, root = overlay_stub()
    order = []
    overlay.subtitle_view = SimpleNamespace(
        sync_window=lambda: order.append("sync"),
        prepare_window_change=lambda: order.append("detach"),
    )
    overlay._on_root_configure(SimpleNamespace(widget=root, width=800, height=280))
    assert order == ["sync"]  # moving without a size change still moves the text layer
    overlay.toggle_borderless()
    assert order[-1] == "detach"
    overlay._on_root_configure(SimpleNamespace(widget=root, width=800, height=280))
    assert order[-1] == "detach"  # no use of a transitional wrapper
    root.run_idle()
    assert order[-1] == "sync"
