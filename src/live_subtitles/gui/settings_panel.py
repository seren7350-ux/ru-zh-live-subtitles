"""Settings window and its controller callbacks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..model_assets import ModelAssetsReport, display_path
from .microphone_selector import MicrophoneSelectorSnapshot
from .commands import bind_start_stop
from .state import SubtitleViewState


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
        on_open_subtitles: Callable[[], None] | None = None,
        on_text_opacity: Callable[[float], None] | None = None,
        on_toggle_outline: Callable[[], None] | None = None,
        on_toggle_toolbar: Callable[[], None] | None = None,
        on_hide: Callable[[], None] | None = None,
        on_restore_defaults: Callable[[], None] | None = None,
        on_open_logs: Callable[[], None] | None = None,
        on_dump_threads: Callable[[], None] | None = None,
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
        self._on_hide = on_hide
        self.last_geometry: str | None = None
        self.window = tk_module.Toplevel(root)
        self.window.title("Subtitle settings")
        self.window.transient(root)
        self.window.configure(background="#20242c", padx=12, pady=10)
        self.window.attributes("-topmost", bool(state.topmost))
        self.window.attributes("-alpha", 1.0)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.bind("<Escape>", lambda _event: self.hide())
        bind_start_stop(self.window, self.on_start_stop)

        if ttk_module is None:
            from tkinter import ttk as ttk_module
        self._checks: dict[str, Any] = {}
        self._body = tk_module.Frame(self.window, background="#20242c")
        self._body.pack(side="bottom", fill="x", pady=(6, 0))
        self.start_stop_button = self._button("Start", on_start_stop)
        clear_button = self._button("Clear display", on_clear)
        exit_button = self._button("Exit application", on_exit, danger=True)
        for button in (self.start_stop_button, clear_button, exit_button):
            button.pack(side="left", fill="none", padx=3, pady=2)
        from .settings_pages import create_settings_pages
        self.pages = create_settings_pages(self.window, root, tk_module, ttk_module)
        self._body = self.pages["General"]
        self.microphone_combobox: Any | None = None
        self.microphone_refresh_button: Any | None = None
        self.microphone_status: Any | None = None
        self._microphone_snapshot: MicrophoneSelectorSnapshot | None = None
        if microphone is not None:
            if ttk_module is None:
                from tkinter import ttk as ttk_module

            self._label("Microphone input")
            microphone_row = tk_module.Frame(self._body, background="#20242c")
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
                self._body,
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

        self._body = self.pages["Diagnostics"]
        self.model_status: Any | None = None
        self.model_recheck_button: Any | None = None
        if models is not None:
            self._label("Model assets")
            self.model_status = tk_module.Label(
                self._body,
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

        self._body = self.pages["General"]
        self.progress_status = self._label("Ready")
        self.russian_button = self._check("Show Russian", "show_russian", on_toggle_russian)
        self.pin_button = self._check("Always on top", "topmost", on_toggle_topmost)
        self._body = self.pages["More"]
        self.border_button = self._check("Borderless window", "borderless", on_toggle_borderless)
        self.toolbar_button = self._check("Show toolbar", "toolbar_visible", on_toggle_toolbar or (lambda: None))
        self._body = self.pages["Appearance"]
        self.outline_button = self._check("Black text outline", "text_outline", on_toggle_outline or (lambda: None))
        self._body = self.pages["More"]
        self.subtitles_button: Any | None = None
        self.subtitles_status: Any | None = None
        if on_open_subtitles is not None:
            self.subtitles_button = self._button("Open subtitles folder", on_open_subtitles)
            self.subtitles_status = tk_module.Label(
                self._body, anchor="w", justify="left", wraplength=360,
                background="#20242c", foreground="#c8ccd4",
            )
            self.subtitles_status.pack(fill="x", pady=(1, 3))

        self._label("Position")
        position_row = tk_module.Frame(self._body, background="#20242c")
        position_row.pack(fill="x", pady=(0, 6))
        for preset in ("top", "bottom"):
            tk_module.Button(
                position_row,
                text=f"Move to {preset}",
                command=lambda selected=preset: on_position(selected),
                **self._button_style(),
            ).pack(side="left", padx=2)

        self._body = self.pages["Appearance"]
        self._label("Background opacity (%)")
        self.opacity_scale = self._scale(
            0, 100, 1, state.opacity * 100, lambda value: on_opacity(float(value) / 100)
        )
        self._label("Text opacity (%)")
        self.text_opacity_scale = self._scale(
            0, 100, 1, state.text_opacity * 100,
            lambda value: on_text_opacity(float(value) / 100) if on_text_opacity else None,
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
        self._body = self.pages["More"]
        if on_restore_defaults is not None:
            self._button("Restore defaults", on_restore_defaults)
        self._label("Double-click subtitles: show / hide toolbar\nRight-click subtitles: settings\nF8: start / stop   Ctrl+Q: exit")
        self._body = self.pages["Diagnostics"]
        if on_open_logs is not None:
            self._button("Open logs folder", on_open_logs)
        if on_dump_threads is not None:
            self._button("Save thread diagnostics", on_dump_threads)
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
            status = "Models ready for offline use."
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
        button = self.tk.Button(self._body, text=text, command=command, **style)
        button.pack(fill="x", pady=2)
        return button

    def _check(self, text: str, name: str, command: Callable[[], None]) -> Any:
        variable = self.tk.BooleanVar(self.window, value=bool(getattr(self.state_model, name)))
        self._checks[name] = variable
        check = self.tk.Checkbutton(
            self._body, text=text, variable=variable, command=command,
            background="#20242c", foreground="#ffffff", selectcolor="#303744",
            activebackground="#20242c", activeforeground="#ffffff", anchor="w",
        )
        check.pack(fill="x", pady=6)
        return check

    def _label(self, text: str) -> Any:
        label = self.tk.Label(
            self._body,
            text=text,
            anchor="w",
            background="#20242c",
            foreground="#d8dbe2",
            justify="left", wraplength=300,
        )
        label.pack(fill="x", pady=(7, 0))
        return label

    def _scale(
        self,
        minimum: float,
        maximum: float,
        resolution: float,
        value: float,
        command: Callable[[str], None],
    ) -> Any:
        scale = self.tk.Scale(
            self._body,
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
        self.progress_status.configure(text=self.state_model.status)
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
        for name, variable in self._checks.items():
            variable.set(bool(getattr(self.state_model, name)))
        self._sync_microphone_controls()
        self._sync_model_controls()
        if self.subtitles_status is not None:
            path = self.state_model.srt_path
            error = self.state_model.srt_error
            text = error or ("Subtitles are saved automatically (SRT)." if path else "SRT recording starts with the next session.")
            self.subtitles_status.config(
                text=text, foreground="#ff8a80" if error else "#c8ccd4",
            )

    def show(self) -> None:
        if not self.exists():
            raise self.tk.TclError("settings panel no longer exists")
        self.window.deiconify()
        if self.last_geometry:
            self.window.geometry(self.last_geometry)
        self.sync()
        self.window.attributes("-alpha", 1.0)
        self.window.attributes("-topmost", bool(self.state_model.topmost))
        self.window.lift()
        self.state_model.settings_visible = True
        self.window.after_idle(self._fit_into_workarea)
        # geometry()/deiconify() are asynchronous WM requests. The idle pass
        # can still see the old position, before the saved geometry is applied.
        # Recheck once after mapping settles; never clamp while the user drags.
        self.window.after(100, self._fit_into_workarea)

    def _fit_into_workarea(self) -> None:
        if not self.exists() or not self.is_visible():
            return
        from .workarea import work_area, fit_rectangle, client_placement_area
        window = self.window
        rect = (window.winfo_x(), window.winfo_y(), window.winfo_width(), window.winfo_height())
        area = work_area(rect, (self.root.winfo_screenwidth(), self.root.winfo_screenheight()))
        area = client_placement_area(window, area, framed=True)
        fitted = fit_rectangle(rect, area)
        if fitted != rect:
            x, y, width, height = fitted
            window.geometry(f"{width}x{height}+{x}+{y}")

    def hide(self) -> None:
        if not self.exists():
            self.state_model.settings_visible = False
            return
        try:
            if self._on_hide is not None:
                self._on_hide()
            self.last_geometry = str(self.window.geometry())
            self.window.withdraw()
        finally:
            self.state_model.settings_visible = False
