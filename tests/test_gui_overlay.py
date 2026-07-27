from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from live_subtitles.gui.overlay import (
    OverlayRenderer,
    SettingsPanel,
    SubtitleOverlay,
    position_coordinates,
)
from live_subtitles.gui.state import SubtitleEntry, SubtitleViewState


class FakeWidget:
    def __init__(self, *_args: object, **kwargs: object) -> None:
        self.options: dict[str, object] = dict(kwargs)
        self.packed = False
        self.bindings: dict[str, object] = {}
        self.value: object = None

    def config(self, **kwargs: object) -> None:
        self.options.update(kwargs)

    configure = config

    def cget(self, name: str) -> object:
        return self.options.get(name)

    def pack(self, **_kwargs: object) -> None:
        self.packed = True

    def pack_propagate(self, value: bool) -> None:
        self.options["pack_propagate"] = value

    def bind(self, event: str, callback: object) -> None:
        self.bindings[event] = callback

    def set(self, value: object) -> None:
        self.value = value


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
    *, state: SubtitleViewState | None = None, running: bool = False
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
        tk_module=tk,
    )
    return panel, root, tk, calls


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


def overlay_stub() -> tuple[SubtitleOverlay, FakeRoot]:
    overlay = SubtitleOverlay.__new__(SubtitleOverlay)
    overlay.tk = FakeTk()
    overlay.root = FakeRoot()
    overlay.state = SubtitleViewState(borderless=True)
    overlay.on_start = lambda: None
    overlay.on_stop = lambda: None
    overlay.on_clear = lambda: None
    overlay.on_exit = lambda: None
    overlay.running = False
    overlay.closing = False
    overlay.settings_panel = None
    overlay._borderless_transition_pending = False
    overlay._window_width = 800
    overlay._window_height = 280
    overlay.render = lambda: None
    return overlay, overlay.root


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
