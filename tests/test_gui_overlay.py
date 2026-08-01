from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from live_subtitles.gui.overlay import (
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    ModelPanelCallbacks,
    MicrophonePanelCallbacks,
    OverlayRenderer,
    ScrollableSubtitleHistory,
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

    def winfo_width(self) -> int:
        return int(self.options.get("width", 640))

    def winfo_height(self) -> int:
        return int(self.options.get("height", 200))

    def winfo_reqheight(self) -> int:
        return int(self.options.get("reqheight", 100))

    def winfo_y(self) -> int:
        return int(self.options.get("y", 0))

    def update_idletasks(self) -> None:
        return None


class FakeCanvas(FakeWidget):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.window_options: dict[str, object] = {}
        self.scroll_movements: list[float] = []
        self.scroll_units: list[int] = []
        self._view = (0.0, 1.0)

    def create_window(self, _coordinates: object, **kwargs: object) -> int:
        self.window_options.update(kwargs)
        return 1

    def itemconfigure(self, _item: object, **kwargs: object) -> None:
        self.window_options.update(kwargs)

    def bbox(self, _target: object) -> tuple[int, int, int, int]:
        return self.options.get(  # type: ignore[return-value]
            "bbox", (0, 0, 640, max(1, len(self.children)) * 100)
        )

    def yview(self, *arguments: object) -> tuple[float, float] | None:
        if arguments:
            if arguments[0] == "moveto":
                self.yview_moveto(float(arguments[1]))
            elif arguments[0] == "scroll":
                self.yview_scroll(int(arguments[1]), str(arguments[2]))
            return None
        return self._view

    def yview_moveto(self, fraction: float) -> None:
        value = min(1.0, max(0.0, float(fraction)))
        self.scroll_movements.append(value)
        self._view = (max(0.0, value - 0.2), value)

    def yview_scroll(self, units: int, _kind: str) -> None:
        self.scroll_units.append(units)
        top = min(0.8, max(0.0, self._view[0] + units * 0.1))
        self._view = (top, min(1.0, top + 0.2))


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
    Canvas = FakeCanvas
    Scrollbar = FakeWidget


class FakeTtk:
    Combobox = FakeWidget


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


def test_renderer_passes_complete_history_instead_of_only_visible_entries() -> None:
    root = FakeRoot()
    widgets = [FakeWidget() for _ in range(4)]
    renderer = OverlayRenderer(
        root,
        status_widget=widgets[0],
        russian_widget=widgets[1],
        chinese_widget=widgets[2],
        error_widget=widgets[3],
    )
    state = SubtitleViewState(history_lines=5, display_lines=2)
    for index in range(5):
        state.add_subtitle(
            SubtitleEntry(index, f"Русский {index}", f"中文 {index}", 0.0, 0.1, 0.2)
        )
    renderer.render(state)
    assert str(widgets[1].options["text"]).splitlines() == [
        f"Русский {index}" for index in range(5)
    ]
    assert str(widgets[2].options["text"]).splitlines() == [
        f"中文 {index}" for index in range(5)
    ]


def test_scrollable_history_preserves_long_unicode_and_uses_actual_width() -> None:
    history = ScrollableSubtitleHistory(
        FakeWidget(),
        tk_module=FakeTk(),
        initial_wraplength=900,
    )
    russian = ("Полный русский текст — без сокращения. " * 20).strip()
    chinese = "完整的中文字幕，不得截断或省略。" * 20
    assert len(russian) >= 500
    assert len(chinese) >= 300
    entries = tuple(
        SubtitleEntry(index, russian, chinese, 0.0, 0.1, 0.2)
        for index in range(5)
    )
    assert history.render_entries(
        entries,
        show_russian=True,
        russian_font_size=20,
        chinese_font_size=34,
    )
    assert len(history.russian_widgets) == 5
    assert len(history.chinese_widgets) == 5
    assert all(widget.options["text"] == russian for widget in history.russian_widgets)
    assert all(widget.options["text"] == chinese for widget in history.chinese_widgets)
    assert history._on_canvas_configure(SimpleNamespace(width=420))
    assert history.wraplength == 396
    assert all(widget.options["wraplength"] == 396 for widget in history.russian_widgets)
    config_counts = [len(widget.config_calls) for widget in history.russian_widgets]
    assert not history._on_canvas_configure(SimpleNamespace(width=420))
    assert [len(widget.config_calls) for widget in history.russian_widgets] == config_counts


def test_scrollable_history_auto_follow_manual_history_and_clear() -> None:
    history = ScrollableSubtitleHistory(
        FakeWidget(),
        tk_module=FakeTk(),
        initial_wraplength=600,
    )
    entries = [SubtitleEntry(1, "Первый", "第一条", 0.0, 0.1, 0.2)]
    history.render_entries(
        entries,
        show_russian=True,
        russian_font_size=20,
        chinese_font_size=34,
    )
    assert history.auto_follow
    assert history.canvas.scroll_movements[-1] == 1.0
    history._on_mousewheel(SimpleNamespace(delta=120))
    assert not history.auto_follow
    history.render_entries(
        (*entries, SubtitleEntry(2, "Второй", "第二条", 0.0, 0.1, 0.2)),
        show_russian=True,
        russian_font_size=20,
        chinese_font_size=34,
    )
    assert history.canvas.scroll_movements[-1] != 1.0
    history.render_entries(
        (),
        show_russian=True,
        russian_font_size=20,
        chinese_font_size=34,
    )
    assert history.auto_follow
    assert history.canvas.options["scrollregion"] == (0, 0, 0, 0)
    assert history.russian_widgets == []
    assert history.chinese_widgets == []


def test_scrollable_history_font_change_rebuilds_complete_widgets() -> None:
    history = ScrollableSubtitleHistory(
        FakeWidget(),
        tk_module=FakeTk(),
        initial_wraplength=600,
    )
    entries = (SubtitleEntry(1, "Русский", "中文", 0.0, 0.1, 0.2),)
    history.render_entries(
        entries,
        show_russian=True,
        russian_font_size=20,
        chinese_font_size=34,
    )
    first_russian = history.russian_widgets[0]
    history.render_entries(
        entries,
        show_russian=True,
        russian_font_size=28,
        chinese_font_size=40,
    )
    assert first_russian.destroyed or first_russian.parent.destroyed
    assert history.russian_widgets[0].options["font"] == ("Segoe UI", 28)
    assert history.chinese_widgets[0].options["font"] == (
        "Microsoft YaHei UI",
        40,
        "bold",
    )


def test_vertical_resize_fits_latest_pair_and_restores_requested_sizes() -> None:
    history = ScrollableSubtitleHistory(
        FakeWidget(),
        tk_module=FakeTk(),
        initial_wraplength=600,
    )
    russian = "Длинный русский текст " * 30
    chinese = "完整的中文长字幕" * 40
    history.render_entries(
        (SubtitleEntry(1, russian, chinese, 0.0, 0.1, 0.2),),
        show_russian=True,
        russian_font_size=20,
        chinese_font_size=34,
    )
    history._entry_frames[-1].options["reqheight"] = 600
    assert history._on_canvas_configure(SimpleNamespace(width=500, height=80))
    assert history.effective_russian_font_size == 8
    assert history.effective_chinese_font_size == 12
    assert history.russian_widgets[0].options["font"] == ("Segoe UI", 8)
    assert history.chinese_widgets[0].options["font"] == (
        "Microsoft YaHei UI",
        12,
        "bold",
    )
    assert history.russian_widgets[0].options["text"] == russian
    assert history.chinese_widgets[0].options["text"] == chinese
    assert history._on_canvas_configure(SimpleNamespace(width=500, height=700))
    assert history.effective_russian_font_size == 20
    assert history.effective_chinese_font_size == 34


def test_new_long_pair_adapts_fonts_without_resizing_root() -> None:
    root = FakeRoot()
    history = ScrollableSubtitleHistory(
        FakeWidget(),
        tk_module=FakeTk(),
        initial_wraplength=600,
    )
    history.render_entries(
        (SubtitleEntry(1, "Long Russian", "Long Chinese", 0.0, 0.1, 0.2),),
        show_russian=True,
        russian_font_size=20,
        chinese_font_size=34,
    )
    history._entry_frames[-1].options["reqheight"] = 500
    history._fit_latest_entry()
    assert root.geometry_calls == []
    assert history.effective_russian_font_size == 8
    assert history.effective_chinese_font_size == 12


def test_oversized_pair_preserves_text_and_follows_its_start() -> None:
    history = ScrollableSubtitleHistory(
        FakeWidget(),
        tk_module=FakeTk(),
        initial_wraplength=600,
    )
    russian = "Russian sentence " * 40
    chinese = "Chinese sentence " * 30
    history.render_entries(
        (SubtitleEntry(1, russian, chinese, 0.0, 0.1, 0.2),),
        show_russian=True,
        russian_font_size=20,
        chinese_font_size=34,
    )
    history._entry_frames[-1].options["reqheight"] = 2000
    history._entry_frames[-1].options["y"] = 300
    history.canvas.options["bbox"] = (0, 0, 640, 2000)
    history._fit_latest_entry()
    assert history.effective_russian_font_size == 8
    assert history.effective_chinese_font_size == 12
    assert history.russian_widgets[0].options["text"] == russian
    assert history.chinese_widgets[0].options["text"] == chinese
    assert history.canvas.scroll_movements[-1] == pytest.approx(0.15)


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
    overlay.running = False
    overlay.closing = False
    overlay.settings_panel = None
    overlay._borderless_transition_pending = False
    overlay._dragging = False
    overlay._resize_session = None
    overlay._window_width = 800
    overlay._window_height = 280
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
