"""Tkinter rendering and persistent controls for the subtitle overlay."""

from __future__ import annotations

from typing import Any, Callable

from .state import SubtitleViewState


STATUS_COLORS = {
    "Preparing": "#f6c85f",
    "Models ready": "#f6c85f",
    "Listening": "#72d572",
    "Stopping": "#f6c85f",
    "Stopped": "#b0b0b0",
    "Fatal error": "#ff6b6b",
    "Ready": "#b0b0b0",
}


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
        russian_widget: Any,
        chinese_widget: Any,
        error_widget: Any,
    ) -> None:
        self.root = root
        self.status_widget = status_widget
        self.russian_widget = russian_widget
        self.chinese_widget = chinese_widget
        self.error_widget = error_widget
        self._drag_offset = (0, 0)

    def render(self, state: SubtitleViewState) -> None:
        entries = state.visible_entries
        russian = "\n".join(entry.russian_text for entry in entries)
        chinese = "\n".join(entry.chinese_text for entry in entries)
        status_prefix = state.status.split("...", 1)[0]
        self.status_widget.config(
            text=state.status,
            foreground=STATUS_COLORS.get(status_prefix, "#b0b0b0"),
        )
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
        tk_module: Any | None = None,
    ) -> None:
        if tk_module is None:
            import tkinter as tk_module

        self.tk = tk_module
        self.root = root
        self.state_model = state
        self.on_start_stop = on_start_stop
        self.is_running = is_running
        self.last_geometry: str | None = None
        self.window = tk_module.Toplevel(root)
        self.window.title("Subtitle settings")
        self.window.transient(root)
        self.window.configure(background="#20242c", padx=12, pady=10)
        self.window.attributes("-topmost", bool(state.topmost))
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.bind("<Escape>", lambda _event: self.hide())

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
    ) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.state = state
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_clear = on_clear
        self.on_exit = on_exit
        self.running = False
        self.closing = False
        self.settings_panel: SettingsPanel | None = None
        self._borderless_transition_pending = False
        self._window_width = max(640, int(self.root.winfo_screenwidth() * 0.8))
        self._window_height = 280

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
        self.root.minsize(520, 180)
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
        self.russian = tk.Label(
            self.content,
            background="#111318",
            foreground="#d8dbe2",
            justify="center",
            anchor="center",
            wraplength=self._window_width - 60,
        )
        self.russian.pack(fill="x", pady=(6, 0))
        self.chinese = tk.Label(
            self.content,
            background="#111318",
            foreground="#ffffff",
            justify="center",
            anchor="center",
            wraplength=self._window_width - 60,
        )
        self.chinese.pack(fill="both", expand=True, pady=(4, 2))
        self.error = tk.Label(
            self.content,
            background="#111318",
            foreground="#ff8a80",
            anchor="center",
            font=("Segoe UI", 9),
        )
        self.error.pack(fill="x")
        self.renderer = OverlayRenderer(
            root,
            status_widget=self.status,
            russian_widget=self.russian,
            chinese_widget=self.chinese,
            error_widget=self.error,
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

    def _bind_interactions_once(self) -> None:
        # A Toplevel bindtag naturally receives descendant events. Binding every
        # child as well would toggle twice (open, then immediately withdraw).
        self.root.bind("<ButtonRelease-3>", self._on_context_request)
        for widget in (self.control_bar, self.drag_area, self.status, self.content):
            widget.bind("<ButtonPress-1>", self._begin_drag)
            widget.bind("<B1-Motion>", self._drag)
        self.root.bind("<Control-q>", lambda _event: self.on_exit())
        self.root.bind("<Control-l>", lambda _event: self.on_clear())
        self.root.bind("<Control-space>", lambda _event: self._start_stop())
        self.root.bind("<Escape>", lambda _event: self.hide_settings_panel())
        self.root.bind("<F11>", lambda _event: self.toggle_borderless())

    def _on_context_request(self, _event: Any) -> None:
        self.toggle_settings_panel()

    def _begin_drag(self, event: Any) -> None:
        self.renderer.begin_drag(event)

    def _drag(self, event: Any) -> None:
        self.state.set_position("floating")
        self.renderer.drag(event)

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
        self.state.borderless = not self.state.borderless
        self._borderless_transition_pending = True
        self.root.overrideredirect(bool(self.state.borderless))
        self.root.after_idle(lambda: self._finish_borderless_toggle(geometry))

    def _finish_borderless_toggle(self, geometry: str) -> None:
        self.root.geometry(geometry)
        self.root.attributes("-topmost", bool(self.state.topmost))
        self.root.attributes("-alpha", float(self.state.opacity))
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
            window_width=max(self._window_width, int(self.root.winfo_width())),
            window_height=max(180, int(self.root.winfo_height())),
            preset=preset,
            current_x=int(self.root.winfo_x()),
            current_y=int(self.root.winfo_y()),
        )
        self.root.geometry(f"+{x}+{y}")
