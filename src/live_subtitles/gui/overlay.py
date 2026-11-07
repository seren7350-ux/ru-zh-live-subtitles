"""Tkinter rendering and persistent controls for the subtitle overlay."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable

from .settings_panel import MicrophonePanelCallbacks, ModelPanelCallbacks, SettingsPanel
from .workarea import window_placement
from .commands import bind_start_stop
from .window_coordinator import WindowCoordinator
from .state import SubtitleViewState
from .single_line import SingleLineSubtitleView, single_line_text
from .windows_taskbar import WindowsTaskbar, bind_window_lifecycle


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
        subtitle_view: SingleLineSubtitleView | None = None,
    ) -> None:
        if subtitle_view is None and (russian_widget is None or chinese_widget is None):
            raise ValueError("Subtitle widgets or a single-line subtitle view are required.")
        self.root = root
        self.status_widget = status_widget
        self.russian_widget = russian_widget
        self.chinese_widget = chinese_widget
        self.subtitle_view = subtitle_view
        self.error_widget = error_widget
        self._drag_offset = (0, 0)

    def render(self, state: SubtitleViewState) -> None:
        entries = state.entries[-1:]
        russian = single_line_text(entries[0].russian_text) if entries else ""
        chinese = single_line_text(entries[0].chinese_text) if entries else ""
        status_prefix = state.status.split("...", 1)[0]
        self.status_widget.config(
            text="Listening" if state.status.startswith("Listening...") else state.status,
            foreground=STATUS_COLORS.get(status_prefix, "#b0b0b0"),
        )
        if self.subtitle_view is not None:
            self.subtitle_view.render_entries(
                entries,
                show_russian=state.show_russian,
                russian_font_size=state.russian_font_size,
                chinese_font_size=state.chinese_font_size,
                text_opacity=state.text_opacity,
                text_outline=state.text_outline,
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
        self.error_widget.config(text=state.latest_error or state.srt_error)

    def begin_drag(self, event: Any) -> None:
        self._drag_offset = (
            int(event.x_root) - int(self.root.winfo_x()),
            int(event.y_root) - int(self.root.winfo_y()),
        )

    def drag(self, event: Any) -> None:
        x = int(event.x_root) - self._drag_offset[0]
        y = int(event.y_root) - self._drag_offset[1]
        self.root.geometry(f"+{x}+{y}")


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
        on_open_subtitles: Callable[[], None] | None = None,
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
        self.on_open_subtitles = on_open_subtitles
        self.on_restore_defaults: Callable[[str], None] | None = None
        self.on_open_logs: Callable[[], None] | None = None
        self.on_dump_threads: Callable[[], None] | None = None
        self.running = False
        self.closing = False
        self.settings_panel: SettingsPanel | None = None
        self._dragging = False
        self._drag_origin: tuple[int, int] | None = None
        self._drag_moved = False
        self._focus_recovery_ready = True
        self._initial_fit_pending = True
        self._resize_session: ResizeSession | None = None
        self._window_width = max(640, int(self.root.winfo_screenwidth() * 0.8))
        self._window_height = 280
        self._minimum_window_height = MIN_WINDOW_HEIGHT
        self._last_root_size = (self._window_width, self._window_height)

        self.root.title("Russian–Chinese Live Subtitles")
        self.root.configure(background="#111318")
        self.root.protocol("WM_DELETE_WINDOW", on_exit)
        from .workarea import work_area, positioned
        initial = (0, 0, self._window_width, self._window_height)
        area = work_area(initial, (root.winfo_screenwidth(), root.winfo_screenheight()))
        x, y, self._window_width, self._window_height = positioned(initial, area, state.position)
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
            highlightbackground="#343a46",
        )
        self.control_bar.pack(fill="x", side="bottom")
        self._toolbar_packed = True
        self.control_bar.pack_propagate(False)
        # Allocate actions before the expanding status. A long device/error
        # label must never consume the space needed to stop or close the app.
        self.actions = tk.Frame(self.control_bar, background="#292e38")
        self.actions.pack(side="right")
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
        self.more_button = self._control_button("More", self._show_more)
        self.more_menu = tk.Menu(root, tearoff=False, background="#24272e",
                                 foreground="#edf0f5", activebackground="#303e58",
                                 activeforeground="#edf0f5", borderwidth=0)
        self.more_menu.add_command(label="Clear display", command=self.on_clear)
        self.more_menu.add_separator()
        self.more_menu.add_command(label="Exit application", accelerator="Ctrl+Q",
                                   command=self.on_exit)

        self.content = tk.Frame(
            root,
            background="#111318",
            padx=24,
            pady=12,
            highlightthickness=1,
            highlightbackground="#292e38",
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
        self.subtitle_view = SingleLineSubtitleView(
            self.content,
            tk_module=tk,
            on_width_changed=self._set_error_wraplength,
            on_minimum_height=self._set_subtitle_minimum_height,
        )
        self.subtitle_view.container.pack(fill="both", expand=True)
        self.renderer = OverlayRenderer(
            root,
            status_widget=self.status,
            error_widget=self.error,
            subtitle_view=self.subtitle_view,
        )
        self.windows = WindowCoordinator(
            self.root, self.state,
            taskbar=WindowsTaskbar() if sys.platform == "win32" else None,
            caption=lambda: self.subtitle_view,
            settings=self._existing_settings_panel,
            closing=lambda: self.closing,
        )
        self._bind_interactions_once()
        self._sync_toolbar()
        self.render()

    def _show_more(self) -> None:
        from .i18n import translate
        # Tk rebuilds/redraws the native Windows menu on entryconfigure, even
        # when the label is unchanged. Configure it once before posting;
        # the live render timer must never mutate a posted menu.
        self.more_menu.entryconfigure(0, label=translate("Clear display", self.state.ui_language))
        self.more_menu.entryconfigure(2, label=translate("Exit application", self.state.ui_language))
        try:
            self.more_menu.tk_popup(self.more_button.winfo_rootx(),
                                    self.more_button.winfo_rooty())
        finally:
            self.more_menu.grab_release()

    def _control_button(
        self, text: str, command: Callable[[], None], *, danger: bool = False
    ) -> Any:
        button = self.tk.Button(
            self.actions,
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

    def _set_subtitle_minimum_height(self, height: int) -> None:
        if not hasattr(self, "subtitle_view"):
            return
        chrome_height = self.root.winfo_height() - self.subtitle_view.canvas.winfo_height()
        minimum = max(MIN_WINDOW_HEIGHT, chrome_height + height)
        if minimum != self._minimum_window_height:
            self._minimum_window_height = minimum
            self.root.minsize(MIN_WINDOW_WIDTH, minimum)
            self.root.after_idle(self._keep_in_workarea)

    def _set_error_wraplength(self, wraplength: int) -> None:
        self.error.configure(wraplength=max(120, int(wraplength)))

    def _bind_interactions_once(self) -> None:
        # A Toplevel bindtag naturally receives descendant events. Binding every
        # child as well would toggle twice (open, then immediately withdraw).
        self.root.bind("<ButtonRelease-3>", self._on_context_request)
        self.root.bind("<Motion>", self._update_resize_cursor)
        self.root.bind("<Leave>", self._clear_resize_cursor)
        self.root.bind("<ButtonPress-1>", self._begin_pointer_action)
        self.root.bind("<B1-Motion>", self._pointer_drag)
        self.root.bind("<ButtonRelease-1>", self._end_pointer_action)
        self.root.bind("<Double-Button-1>", self._toggle_toolbar_event)
        for sequence, callback in (
            ("<Configure>", self._on_root_configure),
            ("<Map>", self._on_root_map),
            ("<Unmap>", self._on_root_unmap),
            ("<FocusIn>", self._on_root_focus),
            ("<FocusOut>", self._on_root_focus_out),
        ):
            bind_window_lifecycle(self.root, sequence, callback)
        self.root.bind("<Control-h>", lambda _event: self.toggle_toolbar())
        self.root.bind("<Control-q>", lambda _event: self.on_exit())
        self.root.bind("<Control-l>", lambda _event: self.on_clear())
        bind_start_stop(self.root, self._start_stop)
        self.root.bind("<Escape>", lambda _event: self.hide_settings_panel())
        self.root.bind("<F11>", lambda _event: self.toggle_borderless())
        bind_caption = getattr(self.subtitle_view, "set_pointer_handlers", None)
        if callable(bind_caption):
            bind_caption({
                "<ButtonPress-1>": self._begin_pointer_action,
                "<B1-Motion>": self._pointer_drag,
                "<ButtonRelease-1>": self._end_pointer_action,
                "<Double-Button-1>": self._toggle_toolbar_event,
                "<ButtonRelease-3>": self._on_context_request,
                "<Motion>": self._update_resize_cursor,
                "<Leave>": self._clear_resize_cursor,
            })

    def _on_context_request(self, _event: Any) -> None:
        self.toggle_settings_panel()

    def _on_root_map(self, event: Any) -> None:
        if event.widget is self.root and not self.closing:
            if getattr(self, "_initial_fit_pending", False):
                self._initial_fit_pending = False
                self.root.after_idle(self._keep_in_workarea)
            self._focus_recovery_ready = True
            self.root.after_idle(self._sync_taskbar)
            self.root.after_idle(self._sync_caption_window)
            self.root.after_idle(self._recover_controls)

    def _on_root_unmap(self, event: Any) -> None:
        if event.widget is self.root:
            self._sync_caption_window()

    def _on_root_focus(self, event: Any) -> None:
        if event.widget is self.root:
            self.root.after_idle(self._sync_caption_window)
            if getattr(self, "_focus_recovery_ready", True):
                self._recover_controls()

    def _on_root_focus_out(self, event: Any) -> None:
        if event.widget is self.root:
            self._focus_recovery_ready = True

    def _suppress_focus_recovery(self) -> None:
        # Withdrawing Settings can return focus directly to the invisible root.
        # Respect dismissal until a later activation or explicit reveal.
        self._focus_recovery_ready = False

    def _sync_caption_window(self) -> None:
        self.windows.sync_caption()

    def _recover_controls(self) -> None:
        if self.closing or self.windows.transition_pending:
            return
        if self.state.opacity > 0 and self.state.toolbar_visible:
            return
        panel = self._existing_settings_panel()
        if panel is None:
            panel = self._create_settings_panel()
        if not panel.is_visible():
            panel.show()

    def _sync_taskbar(self) -> None:
        self.windows.sync_taskbar()

    def reveal(self) -> None:
        """Handle an explicit request to show this instance on the Tk thread."""
        if self.closing:
            return
        self.windows.reveal()
        self._focus_recovery_ready = True
        self._recover_controls()

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
            direction = None if self._pointer_on_control(event) else self._resize_direction_for_event(event)
        self.root.configure(cursor=RESIZE_CURSORS.get(direction, ""))

    def _clear_resize_cursor(self, _event: Any = None) -> None:
        if self._resize_session is None:
            self.root.configure(cursor="")

    def _begin_drag(self, event: Any) -> None:
        if self._resize_direction_for_event(event) is not None:
            self._dragging = False
            return
        self._dragging = True
        self._drag_origin = (int(event.x_root), int(event.y_root))
        self._drag_moved = False
        self.renderer.begin_drag(event)

    def _drag(self, event: Any) -> None:
        if not self._dragging or self._resize_session is not None:
            return
        origin = self._drag_origin
        if not self._drag_moved and origin is not None:
            if max(abs(int(event.x_root) - origin[0]), abs(int(event.y_root) - origin[1])) < 4:
                return
            self._drag_moved = True
        self.state.set_position("floating")
        self.renderer.drag(event)

    @staticmethod
    def _pointer_on_control(event: Any) -> bool:
        widget = getattr(event, "widget", None)
        widget_class = getattr(widget, "winfo_class", lambda: "")()
        return widget_class in {
            "Button", "TButton", "Scale", "TScale", "TCombobox", "Entry", "TEntry",
            "Checkbutton", "TCheckbutton", "Radiobutton", "TRadiobutton", "Scrollbar",
        }

    def _begin_pointer_action(self, event: Any) -> None:
        self._dragging = False
        self._drag_origin = None
        self._resize_session = None
        if self.closing or self._pointer_on_control(event):
            return
        self.windows.activate_from_pointer()
        self._begin_resize(event)
        if self._resize_session is None:
            self._begin_drag(event)

    def _pointer_drag(self, event: Any) -> None:
        if self._resize_session is not None:
            self._resize_drag(event)
        else:
            self._drag(event)

    def _toggle_toolbar_event(self, event: Any) -> str | None:
        if self.closing or self._pointer_on_control(event) or self._resize_direction_for_event(event):
            return None
        self._dragging = False
        self._drag_origin = None
        self._resize_session = None
        self.toggle_toolbar()
        return "break"

    def _sync_toolbar(self) -> None:
        visible = self.state.toolbar_visible
        if visible == self._toolbar_packed:
            return
        if visible:
            self.control_bar.pack(fill="x", side="bottom", before=self.content)
        else:
            self.control_bar.pack_forget()
        self._toolbar_packed = visible
        self.root.after_idle(self._sync_caption_window)

    def toggle_toolbar(self) -> None:
        if self.closing:
            return
        self.state.toolbar_visible = not self.state.toolbar_visible
        self._sync_toolbar()
        self.render()

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
                minimum_height=self._minimum_window_height,
            )
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except (self.tk.TclError, ValueError):
            self._resize_session = None
            self.root.configure(cursor="")

    def _end_pointer_action(self, event: Any) -> None:
        self._dragging = False
        self._drag_origin = None
        self._resize_session = None
        self._update_resize_cursor(event)

    def _on_root_configure(self, event: Any) -> None:
        if getattr(event, "widget", self.root) is not self.root:
            return
        self._sync_caption_window()
        width = int(getattr(event, "width", self.root.winfo_width()))
        height = int(getattr(event, "height", self.root.winfo_height()))
        if width <= 1 or height <= 1:
            return
        current_size = (width, height)
        if current_size == self._last_root_size:
            return
        self._last_root_size = current_size
        if not self.windows.transition_pending:
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
        from .i18n import translate
        tr = lambda text: translate(text, self.state.ui_language)
        pinned_color = "#343a46"
        self.control_bar.config(highlightbackground=pinned_color)
        self.content.config(
            highlightbackground="#292e38"
        )
        self.pin_button.config(text=tr("Pinned" if self.state.topmost else "Unpinned"))
        self.settings_button.config(text=tr("Settings"))
        self.more_button.config(text=tr("More"))
        self.status.configure(text=tr(self.status.cget("text")))
        if self.state.stopping or self.closing:
            primary_text = "Stopping"
        elif self.state.preparing:
            primary_text = "Cancel"
        else:
            primary_text = "Stop" if self.running else "Start"
        self.start_stop_button.config(
            text=tr(primary_text),
            state="disabled" if self.state.stopping or self.closing else "normal",
            background="#303e58" if self.running else "#2365b9",
            activebackground="#3c5174",
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
            on_open_subtitles=self.on_open_subtitles,
            on_text_opacity=self.set_text_opacity,
            on_toggle_outline=self.toggle_text_outline,
            on_toggle_toolbar=self.toggle_toolbar,
            on_hide=self._suppress_focus_recovery,
            on_restore_defaults=self.on_restore_defaults,
            on_open_logs=self.on_open_logs,
            on_dump_threads=self.on_dump_threads,
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
        if self.closing or self.windows.transition_pending:
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
        self.windows.apply_topmost()
        self.render()

    def toggle_borderless(self) -> None:
        if self.closing or self.windows.transition_pending:
            return
        self.hide_settings_panel()
        self._dragging = False
        self._resize_session = None
        self.state.borderless = not self.state.borderless
        self.windows.begin_decoration_change(self.render)

    def set_opacity(self, value: float) -> None:
        self.state.opacity = min(1.0, max(0.0, float(value)))
        self.root.attributes("-alpha", float(self.state.opacity))

    def set_text_opacity(self, value: float) -> None:
        self.state.text_opacity = min(1.0, max(0.0, float(value)))
        self.render()

    def toggle_text_outline(self) -> None:
        self.state.text_outline = not self.state.text_outline
        self.render()

    def set_chinese_font(self, value: int) -> None:
        self.state.chinese_font_size = min(72, max(16, int(value)))
        self.render()

    def set_russian_font(self, value: int) -> None:
        self.state.russian_font_size = min(48, max(10, int(value)))
        self.render()

    def set_position(self, preset: str) -> None:
        self.state.set_position(preset)
        x, y, width, height = window_placement(
            self.root, self.root, self.window_rectangle(), framed=not self.state.borderless, preset=preset
        )
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def window_rectangle(self) -> tuple[int, int, int, int]:
        return (int(self.root.winfo_x()), int(self.root.winfo_y()),
                max(MIN_WINDOW_WIDTH, int(self.root.winfo_width())),
                max(MIN_WINDOW_HEIGHT, int(self.root.winfo_height())))

    def restore_geometry(self, rect: tuple[int, int, int, int]) -> None:
        x, y, width, height = window_placement(
            self.root, self.root, rect, framed=not self.state.borderless
        )
        self.state.set_position("floating")
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _keep_in_workarea(self) -> None:
        if self.closing or self.windows.transition_pending:
            return
        if self.root.winfo_width() <= 1 or self.root.winfo_height() <= 1:
            return
        self.restore_geometry(self.window_rectangle())
