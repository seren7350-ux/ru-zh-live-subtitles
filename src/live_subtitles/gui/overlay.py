"""Tkinter rendering and persistent controls for the subtitle overlay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ..model_assets import ModelAssetsReport, display_path
from .microphone_selector import MicrophoneSelectorSnapshot
from .state import SubtitleEntry, SubtitleViewState


STATUS_COLORS = {
    "Preparing": "#f6c85f",
    "Models ready": "#f6c85f",
    "Listening": "#72d572",
    "Stopping": "#f6c85f",
    "Stopped": "#b0b0b0",
    "Fatal error": "#ff6b6b",
    "Ready": "#b0b0b0",
}

MIN_WINDOW_WIDTH = 520
MIN_WINDOW_HEIGHT = 180
RESIZE_BORDER_PIXELS = 7
MIN_AUTO_FIT_RUSSIAN_FONT_SIZE = 8
MIN_AUTO_FIT_CHINESE_FONT_SIZE = 12
RESIZE_DIRECTIONS = frozenset({"n", "s", "e", "w", "ne", "nw", "se", "sw"})
RESIZE_CURSORS = {
    "n": "sb_v_double_arrow",
    "s": "sb_v_double_arrow",
    "e": "sb_h_double_arrow",
    "w": "sb_h_double_arrow",
    "ne": "top_right_corner",
    "nw": "top_left_corner",
    "se": "bottom_right_corner",
    "sw": "bottom_left_corner",
}


def configure_window_resizing(root: Any) -> None:
    """Enable native decorated resizing and enforce the shared minimum size."""

    root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    root.resizable(True, True)


def resize_direction_at(
    x: int,
    y: int,
    *,
    width: int,
    height: int,
    border: int = RESIZE_BORDER_PIXELS,
) -> str | None:
    """Return the borderless resize direction under a root-relative pointer."""

    if width <= 0 or height <= 0 or border <= 0:
        return None
    horizontal = "w" if x < border else "e" if x >= width - border else ""
    vertical = "n" if y < border else "s" if y >= height - border else ""
    direction = vertical + horizontal
    return direction or None


def resized_geometry(
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    direction: str,
    delta_x: int,
    delta_y: int,
    minimum_width: int = MIN_WINDOW_WIDTH,
    minimum_height: int = MIN_WINDOW_HEIGHT,
) -> tuple[int, int, int, int]:
    """Calculate clamped x/y/width/height for one of eight resize directions."""

    if direction not in RESIZE_DIRECTIONS:
        raise ValueError(f"Unsupported resize direction: {direction}")
    new_x, new_y = int(x), int(y)
    new_width, new_height = int(width), int(height)
    if "w" in direction:
        new_width = max(minimum_width, width - delta_x)
        new_x = x + (width - new_width)
    elif "e" in direction:
        new_width = max(minimum_width, width + delta_x)
    if "n" in direction:
        new_height = max(minimum_height, height - delta_y)
        new_y = y + (height - new_height)
    elif "s" in direction:
        new_height = max(minimum_height, height + delta_y)
    return new_x, new_y, new_width, new_height


@dataclass(frozen=True)
class ResizeSession:
    """Pointer and window geometry captured at the start of a borderless resize."""

    direction: str
    pointer_x: int
    pointer_y: int
    window_x: int
    window_y: int
    window_width: int
    window_height: int


@dataclass(frozen=True)
class MicrophonePanelCallbacks:
    """Callbacks that keep the settings panel independent of the controller."""

    refresh: Callable[[], MicrophoneSelectorSnapshot]
    select: Callable[[int | None], MicrophoneSelectorSnapshot]
    snapshot: Callable[[], MicrophoneSelectorSnapshot]
    can_change: Callable[[], bool]


@dataclass(frozen=True)
class ModelPanelCallbacks:
    """Callbacks for explicit, non-polling model setup actions."""

    recheck: Callable[[], ModelAssetsReport]
    snapshot: Callable[[], ModelAssetsReport]
    open_folder: Callable[[], None]
    open_instructions: Callable[[], None]


class ScrollableSubtitleHistory:
    """A width-aware, vertically scrollable sequence of complete subtitle pairs."""

    def __init__(
        self,
        parent: Any,
        *,
        tk_module: Any,
        initial_wraplength: int,
        on_wraplength_changed: Callable[[int], None] | None = None,
    ) -> None:
        self.tk = tk_module
        self._background = "#111318"
        self._on_wraplength_changed = on_wraplength_changed
        self._content_size: tuple[int, int] | None = None
        self.wraplength = max(120, int(initial_wraplength))
        self._requested_russian_font_size = 20
        self._requested_chinese_font_size = 34
        self.effective_russian_font_size = 20
        self.effective_chinese_font_size = 34
        self.auto_follow = True
        self._signature: tuple[object, ...] | None = None
        self._entry_frames: list[Any] = []
        self.russian_widgets: list[Any] = []
        self.chinese_widgets: list[Any] = []
        self._pending_scroll_fraction: float | None = None
        self._fit_pending = False

        self.container = tk_module.Frame(parent, background=self._background)
        self.scrollbar = tk_module.Scrollbar(
            self.container,
            orient="vertical",
            command=self._on_scrollbar,
        )
        self.scrollbar.pack(side="right", fill="y")
        self.canvas = tk_module.Canvas(
            self.container,
            background=self._background,
            highlightthickness=0,
            borderwidth=0,
            yscrollcommand=self.scrollbar.set,
        )
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk_module.Frame(self.canvas, background=self._background)
        self._body_window = self.canvas.create_window(
            (0, 0), window=self.body, anchor="nw"
        )
        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel(self.canvas)
        self._bind_mousewheel(self.body)

    def _bind_mousewheel(self, widget: Any) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)

    def _on_scrollbar(self, *arguments: object) -> None:
        self.canvas.yview(*arguments)
        self.canvas.after_idle(self._sync_auto_follow)

    def _on_mousewheel(self, event: Any) -> str:
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return "break"
        units = -max(1, abs(delta) // 120) if delta > 0 else max(1, abs(delta) // 120)
        if units < 0:
            self.auto_follow = False
        self.canvas.yview_scroll(units, "units")
        self.canvas.after_idle(self._sync_auto_follow)
        return "break"

    def _sync_auto_follow(self) -> None:
        try:
            _top, bottom = self.canvas.yview()
            self.auto_follow = float(bottom) >= 0.999
        except self.tk.TclError:
            return

    def _on_body_configure(self, _event: Any = None) -> None:
        self._refresh_scrollregion()

    def _refresh_scrollregion(self) -> None:
        try:
            bounds = self.canvas.bbox("all") or (0, 0, 0, 0)
            self.canvas.configure(scrollregion=bounds)
            if self.auto_follow:
                self._follow_latest(bounds)
            elif self._pending_scroll_fraction is not None:
                self.canvas.yview_moveto(self._pending_scroll_fraction)
            self._pending_scroll_fraction = None
        except self.tk.TclError:
            return

    def _follow_latest(self, bounds: tuple[int, int, int, int]) -> None:
        """Show a complete fitting pair, or the start of an oversized pair."""

        if not self._entry_frames:
            self.canvas.yview_moveto(0.0)
            return
        latest = self._entry_frames[-1]
        latest.update_idletasks()
        available_height = max(
            1,
            int(
                self._content_size[1]
                if self._content_size is not None
                else self.canvas.winfo_height()
            ),
        )
        if int(latest.winfo_reqheight()) <= available_height:
            self.canvas.yview_moveto(1.0)
            return
        content_height = max(1, int(bounds[3]) - int(bounds[1]))
        self.canvas.yview_moveto(
            min(1.0, max(0.0, float(latest.winfo_y()) / content_height))
        )

    def _on_canvas_configure(self, event: Any) -> bool:
        """Apply actual viewport size once; return whether layout changed."""

        width = max(1, int(getattr(event, "width", self.canvas.winfo_width())))
        height = max(1, int(getattr(event, "height", self.canvas.winfo_height())))
        wraplength = max(120, width - 24)
        if self._content_size == (width, height) and self.wraplength == wraplength:
            return False
        old_width = self._content_size[0] if self._content_size is not None else None
        old_height = self._content_size[1] if self._content_size is not None else None
        self._content_size = (width, height)
        self.wraplength = wraplength
        if old_width != width:
            self.canvas.itemconfigure(self._body_window, width=width)
            for widget in (*self.russian_widgets, *self.chinese_widgets):
                widget.configure(wraplength=wraplength)
            if self._on_wraplength_changed is not None:
                self._on_wraplength_changed(wraplength)
        if old_height is not None and height > old_height:
            self._restore_requested_fonts()
        self._schedule_latest_fit()
        self.canvas.after_idle(self._refresh_scrollregion)
        return True

    def _apply_font_sizes(self, russian_size: int, chinese_size: int) -> None:
        self.effective_russian_font_size = russian_size
        self.effective_chinese_font_size = chinese_size
        for widget in self.russian_widgets:
            widget.configure(font=("Segoe UI", russian_size))
        for widget in self.chinese_widgets:
            widget.configure(font=("Microsoft YaHei UI", chinese_size, "bold"))

    def _restore_requested_fonts(self) -> None:
        if (
            self.effective_russian_font_size == self._requested_russian_font_size
            and self.effective_chinese_font_size == self._requested_chinese_font_size
        ):
            return
        self._apply_font_sizes(
            self._requested_russian_font_size,
            self._requested_chinese_font_size,
        )

    def _schedule_latest_fit(self) -> None:
        if not self._entry_frames:
            return
        if self._fit_pending:
            return
        self._fit_pending = True
        self.canvas.after_idle(self._fit_latest_entry)

    def _fit_latest_entry(self) -> None:
        """Keep the newest complete RU/ZH pair visible without truncating text."""

        self._fit_pending = False
        if not self._entry_frames:
            return
        try:
            latest = self._entry_frames[-1]
            latest.update_idletasks()
            required_height = max(1, int(latest.winfo_reqheight()))
            available_height = max(
                1,
                int(
                    self._content_size[1]
                    if self._content_size is not None
                    else self.canvas.winfo_height()
                ),
            )
            if required_height <= available_height:
                return
            can_shrink = (
                self.effective_russian_font_size > MIN_AUTO_FIT_RUSSIAN_FONT_SIZE
                or self.effective_chinese_font_size > MIN_AUTO_FIT_CHINESE_FONT_SIZE
            )
            if can_shrink:
                scale = max(
                    0.1,
                    min(
                        0.98,
                        (float(available_height) / required_height) ** 0.5 * 0.95,
                    ),
                )
                russian_size = max(
                    MIN_AUTO_FIT_RUSSIAN_FONT_SIZE,
                    min(
                        self.effective_russian_font_size - 1,
                        round(self.effective_russian_font_size * scale),
                    ),
                )
                chinese_size = max(
                    MIN_AUTO_FIT_CHINESE_FONT_SIZE,
                    min(
                        self.effective_chinese_font_size - 1,
                        round(self.effective_chinese_font_size * scale),
                    ),
                )
                self._apply_font_sizes(russian_size, chinese_size)
                self.canvas.after_idle(self._refresh_scrollregion)
                self._schedule_latest_fit()
                return
            self.canvas.after_idle(self._refresh_scrollregion)
        except self.tk.TclError:
            return

    def _destroy_entries(self) -> None:
        for frame in self._entry_frames:
            frame.destroy()
        self._entry_frames.clear()
        self.russian_widgets.clear()
        self.chinese_widgets.clear()

    def render_entries(
        self,
        entries: Sequence[SubtitleEntry],
        *,
        show_russian: bool,
        russian_font_size: int,
        chinese_font_size: int,
    ) -> bool:
        """Render complete text without truncation and preserve manual history viewing."""

        signature: tuple[object, ...] = (
            show_russian,
            int(russian_font_size),
            int(chinese_font_size),
            tuple(
                (entry.index, entry.russian_text, entry.chinese_text)
                for entry in entries
            ),
        )
        if signature == self._signature:
            return False
        self._requested_russian_font_size = int(russian_font_size)
        self._requested_chinese_font_size = int(chinese_font_size)
        self.effective_russian_font_size = self._requested_russian_font_size
        self.effective_chinese_font_size = self._requested_chinese_font_size
        if not self.auto_follow:
            try:
                self._pending_scroll_fraction = float(self.canvas.yview()[0])
            except self.tk.TclError:
                self._pending_scroll_fraction = None
        self._signature = signature
        self._destroy_entries()
        if not entries:
            self.auto_follow = True
            self._pending_scroll_fraction = None
            self.canvas.configure(scrollregion=(0, 0, 0, 0))
            self.canvas.yview_moveto(0.0)
            return True

        for position, entry in enumerate(entries):
            frame = self.tk.Frame(
                self.body,
                background=self._background,
                padx=8,
                pady=6,
            )
            frame.pack(fill="x", expand=True)
            self._entry_frames.append(frame)
            self._bind_mousewheel(frame)
            if position:
                separator = self.tk.Frame(frame, background="#303540", height=1)
                separator.pack(fill="x", pady=(0, 6))
                self._bind_mousewheel(separator)
            if show_russian:
                russian = self.tk.Label(
                    frame,
                    text=entry.russian_text,
                    background=self._background,
                    foreground="#d8dbe2",
                    justify="center",
                    anchor="center",
                    wraplength=self.wraplength,
                    font=("Segoe UI", self.effective_russian_font_size),
                )
                russian.pack(fill="x", pady=(0, 3))
                self.russian_widgets.append(russian)
                self._bind_mousewheel(russian)
            chinese = self.tk.Label(
                frame,
                text=entry.chinese_text,
                background=self._background,
                foreground="#ffffff",
                justify="center",
                anchor="center",
                wraplength=self.wraplength,
                font=(
                    "Microsoft YaHei UI",
                    self.effective_chinese_font_size,
                    "bold",
                ),
            )
            chinese.pack(fill="x")
            self.chinese_widgets.append(chinese)
            self._bind_mousewheel(chinese)
        self.canvas.after_idle(self._refresh_scrollregion)
        self._schedule_latest_fit()
        return True


def position_coordinates(
    *,
    screen_width: int,
    screen_height: int,
    window_width: int,
    window_height: int,
    preset: str,
    current_x: int = 0,
    current_y: int = 0,
    bottom_safe_distance: int = 70,
) -> tuple[int, int]:
    """Calculate a primary-screen preset without reserving system workspace."""

    if preset not in {"top", "bottom", "floating"}:
        raise ValueError("Position must be one of: top, bottom, floating.")
    if preset == "floating":
        return current_x, current_y
    x = max(0, (screen_width - window_width) // 2)
    if preset == "top":
        return x, 20
    return x, max(0, screen_height - window_height - bottom_safe_distance)


class OverlayRenderer:
    """Render subtitles without touching focus or window-manager state."""

    def __init__(
        self,
        root: Any,
        *,
        status_widget: Any,
        error_widget: Any,
        russian_widget: Any | None = None,
        chinese_widget: Any | None = None,
        history_view: ScrollableSubtitleHistory | None = None,
    ) -> None:
        if history_view is None and (russian_widget is None or chinese_widget is None):
            raise ValueError("Subtitle widgets or a scrollable history view are required.")
        self.root = root
        self.status_widget = status_widget
        self.russian_widget = russian_widget
        self.chinese_widget = chinese_widget
        self.history_view = history_view
        self.error_widget = error_widget
        self._drag_offset = (0, 0)

    def render(self, state: SubtitleViewState) -> None:
        entries = state.entries
        russian = "\n".join(entry.russian_text for entry in entries)
        chinese = "\n".join(entry.chinese_text for entry in entries)
        status_prefix = state.status.split("...", 1)[0]
        self.status_widget.config(
            text=state.status,
            foreground=STATUS_COLORS.get(status_prefix, "#b0b0b0"),
        )
        if self.history_view is not None:
            self.history_view.render_entries(
                entries,
                show_russian=state.show_russian,
                russian_font_size=state.russian_font_size,
                chinese_font_size=state.chinese_font_size,
            )
        else:
            assert self.russian_widget is not None
            assert self.chinese_widget is not None
            self.russian_widget.config(
                text=russian if state.show_russian else "",
                font=("Segoe UI", state.russian_font_size),
            )
            self.chinese_widget.config(
                text=chinese,
                font=("Microsoft YaHei UI", state.chinese_font_size, "bold"),
            )
        self.error_widget.config(text=state.latest_error)

    def begin_drag(self, event: Any) -> None:
        self._drag_offset = (
            int(event.x_root) - int(self.root.winfo_x()),
            int(event.y_root) - int(self.root.winfo_y()),
        )

    def drag(self, event: Any) -> None:
        x = int(event.x_root) - self._drag_offset[0]
        y = int(event.y_root) - self._drag_offset[1]
        self.root.geometry(f"+{x}+{y}")


class SettingsPanel:
    """One persistent Toplevel that is hidden with withdraw, never destroyed to close."""

    def __init__(
        self,
        root: Any,
        state: SubtitleViewState,
        *,
        on_start_stop: Callable[[], None],
        on_clear: Callable[[], None],
        on_toggle_russian: Callable[[], None],
        on_toggle_topmost: Callable[[], None],
        on_toggle_borderless: Callable[[], None],
        on_position: Callable[[str], None],
        on_opacity: Callable[[float], None],
        on_chinese_font: Callable[[int], None],
        on_russian_font: Callable[[int], None],
        on_exit: Callable[[], None],
        is_running: Callable[[], bool],
        microphone: MicrophonePanelCallbacks | None = None,
        models: ModelPanelCallbacks | None = None,
        tk_module: Any | None = None,
        ttk_module: Any | None = None,
    ) -> None:
        if tk_module is None:
            import tkinter as tk_module

        self.tk = tk_module
        self.root = root
        self.state_model = state
        self.on_start_stop = on_start_stop
        self.is_running = is_running
        self.microphone = microphone
        self.models = models
        self.last_geometry: str | None = None
        self.window = tk_module.Toplevel(root)
        self.window.title("Subtitle settings")
        self.window.transient(root)
        self.window.configure(background="#20242c", padx=12, pady=10)
        self.window.attributes("-topmost", bool(state.topmost))
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.bind("<Escape>", lambda _event: self.hide())

        self.microphone_combobox: Any | None = None
        self.microphone_refresh_button: Any | None = None
        self.microphone_status: Any | None = None
        self._microphone_snapshot: MicrophoneSelectorSnapshot | None = None
        if microphone is not None:
            if ttk_module is None:
                from tkinter import ttk as ttk_module

            self._label("Microphone input")
            microphone_row = tk_module.Frame(self.window, background="#20242c")
            microphone_row.pack(fill="x", pady=(2, 2))
            self.microphone_combobox = ttk_module.Combobox(
                microphone_row,
                state="readonly",
            )
            self.microphone_combobox.pack(side="left", fill="x", expand=True)
            self.microphone_combobox.bind(
                "<<ComboboxSelected>>", self._on_microphone_selected
            )
            self.microphone_refresh_button = tk_module.Button(
                microphone_row,
                text="Refresh",
                command=self._refresh_microphones,
                **self._button_style(),
            )
            self.microphone_refresh_button.pack(side="left", padx=(6, 0))
            self.microphone_status = tk_module.Label(
                self.window,
                text="",
                anchor="w",
                justify="left",
                wraplength=360,
                background="#20242c",
                foreground="#c8ccd4",
            )
            self.microphone_status.pack(fill="x", pady=(0, 7))
            # Enumeration is deliberately limited to first creation and the
            # explicit Refresh button. Rendering and showing do not poll.
            self._refresh_microphones(initial=True)

        self.model_status: Any | None = None
        self.model_recheck_button: Any | None = None
        if models is not None:
            self._label("Model assets")
            self.model_status = tk_module.Label(
                self.window,
                text="",
                anchor="w",
                justify="left",
                wraplength=360,
                background="#20242c",
                foreground="#c8ccd4",
            )
            self.model_status.pack(fill="x", pady=(1, 3))
            self.model_recheck_button = self._button(
                "Recheck model assets", self._recheck_models
            )
            self._button("Open model folder", models.open_folder)
            self._button("Open model setup instructions", models.open_instructions)

        self.start_stop_button = self._button("", on_start_stop)
        self._button("Clear", on_clear)
        self.russian_button = self._button("", on_toggle_russian)
        self.pin_button = self._button("", on_toggle_topmost)
        self.border_button = self._button("", on_toggle_borderless)

        self._label("Position")
        position_row = tk_module.Frame(self.window, background="#20242c")
        position_row.pack(fill="x", pady=(0, 6))
        for preset in ("top", "bottom", "floating"):
            tk_module.Button(
                position_row,
                text=preset.title(),
                command=lambda selected=preset: on_position(selected),
                **self._button_style(),
            ).pack(side="left", padx=2)

        self._label("Opacity")
        self.opacity_scale = self._scale(
            0.5, 1.0, 0.01, state.opacity, lambda value: on_opacity(float(value))
        )
        self._label("Chinese font size")
        self.chinese_scale = self._scale(
            16,
            72,
            1,
            state.chinese_font_size,
            lambda value: on_chinese_font(int(float(value))),
        )
        self._label("Russian font size")
        self.russian_scale = self._scale(
            10,
            48,
            1,
            state.russian_font_size,
            lambda value: on_russian_font(int(float(value))),
        )
        self._button("Exit", on_exit, danger=True)
        self.sync()

    def _refresh_microphones(self, *, initial: bool = False) -> None:
        if self.microphone is None:
            return
        if not initial and not self._can_change_microphone():
            self.sync()
            return
        self._microphone_snapshot = self.microphone.refresh()
        self._sync_microphone_controls()

    def _on_microphone_selected(self, _event: Any = None) -> None:
        if (
            self.microphone is None
            or self.microphone_combobox is None
            or not self._can_change_microphone()
        ):
            self.sync()
            return
        position = int(self.microphone_combobox.current())
        snapshot = self._microphone_snapshot or self.microphone.snapshot()
        if not 0 <= position < len(snapshot.choices):
            return
        self._microphone_snapshot = self.microphone.select(
            snapshot.choices[position].device_index
        )
        self._sync_microphone_controls()

    def _can_change_microphone(self) -> bool:
        return bool(
            self.microphone is not None
            and self.microphone.can_change()
            and not self.is_running()
            and not self.state_model.preparing
            and not self.state_model.stopping
        )

    def _sync_microphone_controls(self) -> None:
        if (
            self.microphone is None
            or self.microphone_combobox is None
            or self.microphone_refresh_button is None
            or self.microphone_status is None
        ):
            return
        snapshot = self.microphone.snapshot()
        self._microphone_snapshot = snapshot
        can_change = self._can_change_microphone()
        self.microphone_combobox.config(
            values=tuple(choice.label for choice in snapshot.choices),
            state="readonly" if can_change else "disabled",
        )
        self.microphone_combobox.current(snapshot.selected_position)
        self.microphone_refresh_button.config(
            state="normal" if can_change else "disabled"
        )
        status = (
            snapshot.status
            if can_change
            else "Stop subtitles before changing the microphone."
        )
        self.microphone_status.config(text=status)

    def _recheck_models(self) -> None:
        if self.models is None:
            return
        self.models.recheck()
        self._sync_model_controls()

    def _sync_model_controls(self) -> None:
        if self.models is None or self.model_status is None:
            return
        report = self.models.snapshot()
        if report.ready:
            status = "Ready. All pinned model assets passed the quick offline check."
        else:
            missing = ", ".join(item.model_id for item in report.missing_models)
            status = (
                f"Model setup required: {missing}. Root: "
                f"{display_path(report.model_root)}"
            )
        self.model_status.config(text=status)

    @staticmethod
    def _button_style() -> dict[str, Any]:
        return {
            "background": "#3a3f4b",
            "foreground": "#ffffff",
            "activebackground": "#505766",
            "activeforeground": "#ffffff",
            "relief": "flat",
            "padx": 8,
        }

    def _button(
        self, text: str, command: Callable[[], None], *, danger: bool = False
    ) -> Any:
        style = self._button_style()
        if danger:
            style["background"] = "#a83232"
        button = self.tk.Button(self.window, text=text, command=command, **style)
        button.pack(fill="x", pady=2)
        return button

    def _label(self, text: str) -> None:
        self.tk.Label(
            self.window,
            text=text,
            anchor="w",
            background="#20242c",
            foreground="#d8dbe2",
        ).pack(fill="x", pady=(7, 0))

    def _scale(
        self,
        minimum: float,
        maximum: float,
        resolution: float,
        value: float,
        command: Callable[[str], None],
    ) -> Any:
        scale = self.tk.Scale(
            self.window,
            from_=minimum,
            to=maximum,
            resolution=resolution,
            orient="horizontal",
            command=command,
            background="#20242c",
            foreground="#ffffff",
            highlightthickness=0,
        )
        scale.set(value)
        scale.pack(fill="x")
        return scale

    def exists(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except self.tk.TclError:
            return False

    def is_visible(self) -> bool:
        if not self.exists():
            return False
        try:
            return str(self.window.state()) != "withdrawn"
        except self.tk.TclError:
            return False

    def sync(self) -> None:
        if not self.exists():
            return
        running = self.is_running()
        stopping = self.state_model.stopping
        if stopping:
            primary_text = "Stopping"
        elif self.state_model.preparing:
            primary_text = "Cancel"
        else:
            primary_text = "Stop" if running else "Start"
        self.start_stop_button.config(
            text=primary_text,
            state="disabled" if stopping else "normal",
            background="#b63838" if running else "#2166a5",
        )
        self.russian_button.config(
            text=f"Show Russian: {'on' if self.state_model.show_russian else 'off'}"
        )
        self.pin_button.config(
            text=f"Always on top: {'pinned' if self.state_model.topmost else 'unpinned'}"
        )
        self.border_button.config(
            text=f"Borderless: {'on' if self.state_model.borderless else 'off'}"
        )
        self._sync_microphone_controls()
        self._sync_model_controls()

    def show(self) -> None:
        if not self.exists():
            raise self.tk.TclError("settings panel no longer exists")
        self.window.deiconify()
        if self.last_geometry:
            self.window.geometry(self.last_geometry)
        self.sync()
        self.window.attributes("-topmost", bool(self.state_model.topmost))
        self.window.lift()
        self.state_model.settings_visible = True

    def hide(self) -> None:
        if not self.exists():
            self.state_model.settings_visible = False
            return
        try:
            self.last_geometry = str(self.window.geometry())
            self.window.withdraw()
        finally:
            self.state_model.settings_visible = False


class SubtitleOverlay:
    """One subtitle root, one persistent control bar, and one optional settings panel."""

    def __init__(
        self,
        root: Any,
        state: SubtitleViewState,
        *,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_clear: Callable[[], None],
        on_exit: Callable[[], None],
        microphone: MicrophonePanelCallbacks | None = None,
        models: ModelPanelCallbacks | None = None,
    ) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.state = state
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_clear = on_clear
        self.on_exit = on_exit
        self.microphone_callbacks = microphone
        self.model_callbacks = models
        self.running = False
        self.closing = False
        self.settings_panel: SettingsPanel | None = None
        self._borderless_transition_pending = False
        self._dragging = False
        self._resize_session: ResizeSession | None = None
        self._window_width = max(640, int(self.root.winfo_screenwidth() * 0.8))
        self._window_height = 280
        self._last_root_size = (self._window_width, self._window_height)

        self.root.title("Russian–Chinese Live Subtitles")
        self.root.configure(background="#111318")
        self.root.protocol("WM_DELETE_WINDOW", on_exit)
        x, y = position_coordinates(
            screen_width=self.root.winfo_screenwidth(),
            screen_height=self.root.winfo_screenheight(),
            window_width=self._window_width,
            window_height=self._window_height,
            preset=state.position,
        )
        self.root.geometry(f"{self._window_width}x{self._window_height}+{x}+{y}")
        configure_window_resizing(self.root)
        self.root.attributes("-topmost", bool(state.topmost))
        self.root.attributes("-alpha", float(state.opacity))
        self.root.overrideredirect(bool(state.borderless))

        self.control_bar = tk.Frame(
            root,
            background="#292e38",
            height=38,
            padx=6,
            pady=3,
            highlightthickness=1,
            highlightbackground="#547aa5" if state.topmost else "#404550",
        )
        self.control_bar.pack(fill="x", side="bottom")
        self.control_bar.pack_propagate(False)
        self.drag_area = tk.Label(
            self.control_bar,
            text="⋮⋮  Drag",
            background="#292e38",
            foreground="#c8ccd4",
            width=9,
            anchor="w",
        )
        self.drag_area.pack(side="left")
        self.status = tk.Label(
            self.control_bar,
            background="#292e38",
            foreground="#b0b0b0",
            anchor="w",
            font=("Segoe UI", 9),
        )
        self.status.pack(side="left", fill="x", expand=True)
        self.start_stop_button = self._control_button("Start", self._start_stop)
        self.pin_button = self._control_button("Pinned", self.toggle_topmost)
        self.settings_button = self._control_button("Settings", self.toggle_settings_panel)
        self.exit_button = self._control_button("Exit", self.on_exit, danger=True)

        self.content = tk.Frame(
            root,
            background="#111318",
            padx=24,
            pady=12,
            highlightthickness=1,
            highlightbackground="#547aa5" if state.topmost else "#111318",
        )
        self.content.pack(fill="both", expand=True)
        self.error = tk.Label(
            self.content,
            background="#111318",
            foreground="#ff8a80",
            anchor="center",
            font=("Segoe UI", 9),
            wraplength=max(120, self._window_width - 60),
        )
        self.error.pack(fill="x", side="bottom")
        self.history_view = ScrollableSubtitleHistory(
            self.content,
            tk_module=tk,
            initial_wraplength=max(120, self._window_width - 60),
            on_wraplength_changed=self._set_error_wraplength,
        )
        self.history_view.container.pack(fill="both", expand=True)
        self.renderer = OverlayRenderer(
            root,
            status_widget=self.status,
            error_widget=self.error,
            history_view=self.history_view,
        )
        self._bind_interactions_once()
        self.render()

    def _control_button(
        self, text: str, command: Callable[[], None], *, danger: bool = False
    ) -> Any:
        button = self.tk.Button(
            self.control_bar,
            text=text,
            command=command,
            background="#a83232" if danger else "#3a3f4b",
            foreground="#ffffff",
            activebackground="#505766",
            activeforeground="#ffffff",
            relief="flat",
            padx=9,
        )
        button.pack(side="left", padx=2)
        return button

    def _set_error_wraplength(self, wraplength: int) -> None:
        self.error.configure(wraplength=max(120, int(wraplength)))

    def _bind_interactions_once(self) -> None:
        # A Toplevel bindtag naturally receives descendant events. Binding every
        # child as well would toggle twice (open, then immediately withdraw).
        self.root.bind("<ButtonRelease-3>", self._on_context_request)
        for widget in (self.drag_area, self.status):
            widget.bind("<ButtonPress-1>", self._begin_drag)
            widget.bind("<B1-Motion>", self._drag)
        self.root.bind("<Motion>", self._update_resize_cursor)
        self.root.bind("<Leave>", self._clear_resize_cursor)
        self.root.bind("<ButtonPress-1>", self._begin_resize)
        self.root.bind("<B1-Motion>", self._resize_drag)
        self.root.bind("<ButtonRelease-1>", self._end_pointer_action)
        self.root.bind("<Configure>", self._on_root_configure)
        self.root.bind("<Control-q>", lambda _event: self.on_exit())
        self.root.bind("<Control-l>", lambda _event: self.on_clear())
        self.root.bind("<Control-space>", lambda _event: self._start_stop())
        self.root.bind("<Escape>", lambda _event: self.hide_settings_panel())
        self.root.bind("<F11>", lambda _event: self.toggle_borderless())

    def _on_context_request(self, _event: Any) -> None:
        self.toggle_settings_panel()

    def _root_relative_pointer(self, event: Any) -> tuple[int, int]:
        root_x_getter = getattr(self.root, "winfo_rootx", self.root.winfo_x)
        root_y_getter = getattr(self.root, "winfo_rooty", self.root.winfo_y)
        return (
            int(event.x_root) - int(root_x_getter()),
            int(event.y_root) - int(root_y_getter()),
        )

    def _resize_direction_for_event(self, event: Any) -> str | None:
        if not self.state.borderless:
            return None
        pointer_x, pointer_y = self._root_relative_pointer(event)
        return resize_direction_at(
            pointer_x,
            pointer_y,
            width=int(self.root.winfo_width()),
            height=int(self.root.winfo_height()),
        )

    def _update_resize_cursor(self, event: Any) -> None:
        if self._resize_session is not None:
            direction = self._resize_session.direction
        else:
            direction = self._resize_direction_for_event(event)
        self.root.configure(cursor=RESIZE_CURSORS.get(direction, ""))

    def _clear_resize_cursor(self, _event: Any = None) -> None:
        if self._resize_session is None:
            self.root.configure(cursor="")

    def _begin_drag(self, event: Any) -> None:
        if self._resize_direction_for_event(event) is not None:
            self._dragging = False
            return
        self._dragging = True
        self.renderer.begin_drag(event)

    def _drag(self, event: Any) -> None:
        if not self._dragging or self._resize_session is not None:
            return
        self.state.set_position("floating")
        self.renderer.drag(event)

    def _begin_resize(self, event: Any) -> None:
        direction = self._resize_direction_for_event(event)
        if direction is None:
            return
        self._dragging = False
        self.state.set_position("floating")
        self._resize_session = ResizeSession(
            direction=direction,
            pointer_x=int(event.x_root),
            pointer_y=int(event.y_root),
            window_x=int(self.root.winfo_x()),
            window_y=int(self.root.winfo_y()),
            window_width=int(self.root.winfo_width()),
            window_height=int(self.root.winfo_height()),
        )
        self.root.configure(cursor=RESIZE_CURSORS[direction])

    def _resize_drag(self, event: Any) -> None:
        session = self._resize_session
        if session is None:
            return
        try:
            x, y, width, height = resized_geometry(
                x=session.window_x,
                y=session.window_y,
                width=session.window_width,
                height=session.window_height,
                direction=session.direction,
                delta_x=int(event.x_root) - session.pointer_x,
                delta_y=int(event.y_root) - session.pointer_y,
            )
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except (self.tk.TclError, ValueError):
            self._resize_session = None
            self.root.configure(cursor="")

    def _end_pointer_action(self, event: Any) -> None:
        self._dragging = False
        self._resize_session = None
        self._update_resize_cursor(event)

    def _on_root_configure(self, event: Any) -> None:
        if getattr(event, "widget", self.root) is not self.root:
            return
        width = int(getattr(event, "width", self.root.winfo_width()))
        height = int(getattr(event, "height", self.root.winfo_height()))
        if width <= 1 or height <= 1:
            return
        current_size = (width, height)
        if current_size == self._last_root_size:
            return
        self._last_root_size = current_size
        if not self._borderless_transition_pending:
            self.state.set_position("floating")

    def _start_stop(self) -> None:
        if self.state.stopping or self.closing:
            return
        if self.running:
            self.on_stop()
        else:
            self.on_start()

    def render(self) -> None:
        self.renderer.render(self.state)
        pinned_color = "#547aa5" if self.state.topmost else "#404550"
        self.control_bar.config(highlightbackground=pinned_color)
        self.content.config(
            highlightbackground="#547aa5" if self.state.topmost else "#111318"
        )
        self.pin_button.config(text="Pinned" if self.state.topmost else "Unpinned")
        if self.state.stopping or self.closing:
            primary_text = "Stopping"
        elif self.state.preparing:
            primary_text = "Cancel"
        else:
            primary_text = "Stop" if self.running else "Start"
        self.start_stop_button.config(
            text=primary_text,
            state="disabled" if self.state.stopping or self.closing else "normal",
            background="#b63838" if self.running else "#2166a5",
            activebackground="#d14949" if self.running else "#2d7fc4",
        )
        panel = self._existing_settings_panel()
        if panel is not None:
            panel.sync()

    def set_running(self, running: bool, *, closing: bool = False) -> None:
        self.running = running
        self.closing = closing
        self.render()

    def _create_settings_panel(self) -> SettingsPanel:
        panel = SettingsPanel(
            self.root,
            self.state,
            on_start_stop=self._start_stop,
            on_clear=self.on_clear,
            on_toggle_russian=self.toggle_russian,
            on_toggle_topmost=self.toggle_topmost,
            on_toggle_borderless=self.toggle_borderless,
            on_position=self.set_position,
            on_opacity=self.set_opacity,
            on_chinese_font=self.set_chinese_font,
            on_russian_font=self.set_russian_font,
            on_exit=self.on_exit,
            is_running=lambda: self.running,
            microphone=self.microphone_callbacks,
            models=self.model_callbacks,
        )
        self.settings_panel = panel
        return panel

    def _existing_settings_panel(self) -> SettingsPanel | None:
        panel = self.settings_panel
        if panel is None:
            return None
        if panel.exists():
            return panel
        self.settings_panel = None
        self.state.settings_visible = False
        return None

    def toggle_settings_panel(self) -> None:
        if self.closing or self._borderless_transition_pending:
            return
        panel = self._existing_settings_panel()
        if panel is None:
            panel = self._create_settings_panel()
            panel.show()
            return
        if panel.is_visible():
            panel.hide()
        else:
            panel.show()

    def hide_settings_panel(self) -> None:
        panel = self._existing_settings_panel()
        if panel is not None:
            panel.hide()
        else:
            self.state.settings_visible = False

    def close_popover(self) -> None:
        """Compatibility name used by the runtime; persistent panels are withdrawn."""

        self.hide_settings_panel()

    def toggle_russian(self) -> None:
        self.state.show_russian = not self.state.show_russian
        self.render()

    def toggle_topmost(self) -> None:
        self.state.topmost = not self.state.topmost
        self.root.attributes("-topmost", bool(self.state.topmost))
        panel = self._existing_settings_panel()
        if panel is not None:
            panel.window.attributes("-topmost", bool(self.state.topmost))
        self.render()

    def toggle_borderless(self) -> None:
        if self.closing or self._borderless_transition_pending:
            return
        geometry = str(self.root.geometry())
        self.hide_settings_panel()
        self._dragging = False
        self._resize_session = None
        self.state.borderless = not self.state.borderless
        self._borderless_transition_pending = True
        self.root.overrideredirect(bool(self.state.borderless))
        self.root.after_idle(lambda: self._finish_borderless_toggle(geometry))

    def _finish_borderless_toggle(self, geometry: str) -> None:
        self.root.geometry(geometry)
        self.root.attributes("-topmost", bool(self.state.topmost))
        self.root.attributes("-alpha", float(self.state.opacity))
        self.root.resizable(True, True)
        self.root.configure(cursor="")
        self._borderless_transition_pending = False
        self.render()

    def set_opacity(self, value: float) -> None:
        self.state.opacity = min(1.0, max(0.5, float(value)))
        self.root.attributes("-alpha", float(self.state.opacity))

    def set_chinese_font(self, value: int) -> None:
        self.state.chinese_font_size = min(72, max(16, int(value)))
        self.render()

    def set_russian_font(self, value: int) -> None:
        self.state.russian_font_size = min(48, max(10, int(value)))
        self.render()

    def set_position(self, preset: str) -> None:
        self.state.set_position(preset)
        x, y = position_coordinates(
            screen_width=self.root.winfo_screenwidth(),
            screen_height=self.root.winfo_screenheight(),
            window_width=max(MIN_WINDOW_WIDTH, int(self.root.winfo_width())),
            window_height=max(MIN_WINDOW_HEIGHT, int(self.root.winfo_height())),
            preset=preset,
            current_x=int(self.root.winfo_x()),
            current_y=int(self.root.winfo_y()),
        )
        self.root.geometry(f"+{x}+{y}")
