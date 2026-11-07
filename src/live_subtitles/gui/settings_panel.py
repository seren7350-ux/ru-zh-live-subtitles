"""Settings window and its controller callbacks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .. import __version__
from ..model_assets import ModelAssetsReport, display_path
from .microphone_selector import MicrophoneSelectorSnapshot
from .workarea import window_placement
from .commands import bind_start_stop
from .state import SubtitleViewState
from . import settings_theme as theme
from .settings_controls import NumericScale


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
        on_restore_defaults: Callable[[str], None] | None = None,
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
        # An owned Windows dialog must stay above its owner even when the
        # owner is activated. Settings is modeless: keep the Tk lifetime parent,
        # but do not establish a native transient owner. Both windows share the
        # selected topmost band and otherwise follow normal activation order.
        self.window.configure(background=theme.SURFACE, padx=0, pady=0)
        self.window.attributes("-topmost", bool(state.topmost))
        self.window.attributes("-alpha", 1.0)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.bind("<Escape>", lambda _event: self.hide())
        self.window.bind("<Control-q>", lambda _event: on_exit())
        bind_start_stop(self.window, self.on_start_stop)

        if ttk_module is None:
            from tkinter import ttk as ttk_module
        self.ttk = ttk_module
        theme.install(ttk_module, root, tk_module)
        self._checks: dict[str, Any] = {}
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
            microphone_row = tk_module.Frame(self._body, background=theme.SURFACE)
            microphone_row.pack(fill="x", pady=(2, 2))
            self.microphone_combobox = ttk_module.Combobox(
                microphone_row,
                state="readonly", style="Settings.TCombobox",
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
                background=theme.SURFACE,
                foreground=theme.MUTED,
            )
            self.microphone_status.pack(fill="x", pady=(0, 7))
            # Enumeration is deliberately limited to first creation and the
            # explicit Refresh button. Rendering and showing do not poll.
            self._refresh_microphones(initial=True)

        self._section("Session")
        self.progress_status = self._label("Ready")
        self.input_error = self._label("")
        self.input_error.configure(foreground=theme.ERROR)
        self.input_error.pack_forget()
        self.input_model_status = self._label("")
        self.input_model_help = None
        if models is not None:
            self.input_model_help = self._button("Model setup help", models.open_instructions)
        self.start_stop_button = self._button("Start", on_start_stop)
        self._label("F8 to start or stop. Audio is processed on this computer.")

        self._body = self.pages["Diagnostics"]
        self._label(f"Russian–Chinese Live Subtitles {__version__}")
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
                background=theme.SURFACE,
                foreground=theme.MUTED,
            )
            self.model_status.pack(fill="x", pady=(1, 3))
            self.model_recheck_button = self._button(
                "Recheck model assets", self._recheck_models
            )
            self._button("Open model folder", models.open_folder)
            self._button("Open model setup instructions", models.open_instructions)

        self._body = self.pages["Appearance"]
        self.visibility_note = self._label("")
        self._appearance_heading = self._section("Language & size")
        self.russian_button = self._check("Show Russian", "show_russian", on_toggle_russian)
        self.chinese_scale = self._scale(
            16, 72, 1, state.chinese_font_size,
            lambda value: on_chinese_font(int(float(value))), label="Chinese size (pt)")
        self.russian_scale = self._scale(
            10, 48, 1, state.russian_font_size,
            lambda value: on_russian_font(int(float(value))), label="Russian size (pt)")
        self._body = self.pages["More"]
        self._section("Interface language")
        from .i18n import LANGUAGE_NAMES, LANGUAGES
        self.language_selector = ttk_module.Combobox(
            self._body, state="readonly", values=LANGUAGE_NAMES,
            style="Settings.TCombobox", width=16)
        self.language_selector.current(LANGUAGES.index(state.ui_language))
        self.language_selector.pack(anchor="w", pady=(0, 8))
        self.language_selector.bind("<<ComboboxSelected>>", self._change_language)
        self._section("Window behavior")
        self.pin_button = self._check("Always on top", "topmost", on_toggle_topmost)
        self._body = self.pages["More"]
        self.border_button = self._check("Borderless window", "borderless", on_toggle_borderless)
        self.toolbar_button = self._check("Show toolbar", "toolbar_visible", on_toggle_toolbar or (lambda: None))
        self._body = self.pages["More"]
        self._section("Subtitle files")
        self.subtitles_button: Any | None = None
        self.subtitles_status: Any | None = None
        if on_open_subtitles is not None:
            self.subtitles_button = self._button("Open subtitles folder", on_open_subtitles)
            self.subtitles_status = tk_module.Label(
                self._body, anchor="w", justify="left", wraplength=360,
                background=theme.SURFACE, foreground=theme.MUTED,
            )
            self.subtitles_status.pack(fill="x", pady=(1, 3))

        self._label("Position")
        position_row = tk_module.Frame(self._body, background=theme.SURFACE)
        position_row.pack(fill="x", pady=(0, 6))
        for preset in ("top", "bottom"):
            tk_module.Button(
                position_row,
                text=f"Move to {preset}",
                command=lambda selected=preset: on_position(selected),
                **self._button_style(),
            ).pack(side="left", padx=2)

        self._body = self.pages["Appearance"]
        self._section("Background & text")
        self.opacity_scale = self._scale(
            0, 100, 1, state.opacity * 100, lambda value: on_opacity(float(value) / 100), label="Background opacity (%)"
        )
        self.text_opacity_scale = self._scale(
            0, 100, 1, state.text_opacity * 100,
            lambda value: on_text_opacity(float(value) / 100) if on_text_opacity else None,
            label="Text opacity (%)",
        )
        self.outline_button = self._check("Black text outline", "text_outline", on_toggle_outline or (lambda: None))
        self._body = self.pages["More"]
        self._shortcuts_expanded = False
        self.shortcuts_button = self._button("Show shortcuts", self._toggle_shortcuts)
        self.shortcuts_note = self._label("Double-click subtitles: show / hide toolbar\nRight-click subtitles: settings\nF8: start / stop   Ctrl+Q: exit")
        self.shortcuts_note.pack_forget()
        self._body = self.pages["Diagnostics"]
        self._button("Clear display", on_clear)
        self._button("Exit application", on_exit)
        if on_open_logs is not None:
            self._button("Open logs folder", on_open_logs)
        if on_dump_threads is not None:
            self._button("Save thread diagnostics", on_dump_threads)
        self.input_reset_button = None
        if on_restore_defaults is not None:
            for page in ("Appearance", "General", "More"):
                self._body = self.pages[page]
                button = self._button(
                    "Reset this page", lambda name=page: self._confirm_reset(name, on_restore_defaults))
                if page == "General":
                    self.input_reset_button = button
        self.sync()

    def _confirm_reset(self, page: str, callback: Callable[[str], None]) -> None:
        from tkinter import messagebox
        from .i18n import translate
        if page == "General" and not self._can_change_microphone():
            return
        language = self.state_model.ui_language
        if messagebox.askyesno(
            translate("Reset this page", language),
            translate("Reset only this page? Interface language and other pages are kept.", language),
            parent=self.window, default="no",
        ):
            callback(page)

    def _toggle_shortcuts(self) -> None:
        self._shortcuts_expanded = not self._shortcuts_expanded
        self.shortcuts_button.configure(
            text="Hide shortcuts" if self._shortcuts_expanded else "Show shortcuts")
        if self._shortcuts_expanded:
            self.shortcuts_note.pack(fill="x", pady=(7, 0), after=self.shortcuts_button)
        else:
            self.shortcuts_note.pack_forget()
        self.sync()

    def _change_language(self, _event=None) -> None:
        from .i18n import LANGUAGES
        index = self.language_selector.current()
        if 0 <= index < len(LANGUAGES):
            self.state_model.ui_language = LANGUAGES[index]
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
        from .i18n import translate
        self._microphone_snapshot = snapshot
        can_change = self._can_change_microphone()
        self.microphone_combobox.config(
            values=tuple(translate(choice.label, self.state_model.ui_language)
                         if choice.device_index is None else choice.label
                         for choice in snapshot.choices),
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
            self.input_model_status.configure(text="Demo mode · no microphone or models required.",
                                              foreground=theme.MUTED)
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
        self.input_model_status.configure(
            text="Models ready for offline use." if report.ready else "Model files need attention before starting.",
            foreground=theme.MUTED if report.ready else theme.ERROR)
        if self.input_model_help is not None:
            if report.ready:
                self.input_model_help.pack_forget()
            else:
                self.input_model_help.pack(anchor="w", pady=6, before=self.start_stop_button)

    @staticmethod
    def _button_style() -> dict[str, Any]:
        return {
            "background": theme.CONTROL,
            "foreground": theme.TEXT,
            "activebackground": theme.SELECTED,
            "activeforeground": theme.ACCENT,
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
        button.pack(anchor="w", pady=5, ipady=3)
        return button

    def _section(self, text: str) -> Any:
        heading = self.tk.Label(self._body, text=text, anchor="w", background=theme.SURFACE,
                                foreground=theme.MUTED, font=("Segoe UI", 9, "bold"))
        heading.pack(fill="x", pady=(12, 4))
        return heading

    def _check(self, text: str, name: str, command: Callable[[], None]) -> Any:
        variable = self.tk.BooleanVar(self.window, value=bool(getattr(self.state_model, name)))
        self._checks[name] = variable
        row = self.tk.Frame(self._body, background=theme.SURFACE)
        row.pack(fill="x", pady=7)
        self.tk.Label(row, text=text, anchor="w", background=theme.SURFACE,
                      foreground=theme.TEXT).pack(side="left")
        check = self.ttk.Checkbutton(row, text=text, variable=variable, command=command,
                                     style="Settings.TCheckbutton", takefocus=True)
        check.pack(side="right")
        return check

    def _label(self, text: str) -> Any:
        label = self.tk.Label(
            self._body,
            text=text,
            anchor="w",
            background=theme.SURFACE,
            foreground=theme.TEXT,
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
        *, label: str,
    ) -> Any:
        def changed(value: str) -> None:
            command(value)
            self._sync_visibility_note()
        return NumericScale(self._body, tk=self.tk, ttk=self.ttk, label=label,
                            minimum=minimum, maximum=maximum, value=value, command=changed)

    def _sync_visibility_note(self) -> None:
        hidden = self.state_model.opacity == 0 or self.state_model.text_opacity == 0
        self.visibility_note.configure(text="Hidden at 0%. Settings remain available." if hidden else "")
        if hidden:
            self.visibility_note.pack(fill="x", pady=(0, 5), before=self._appearance_heading)
        else:
            self.visibility_note.pack_forget()

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
        self._sync_visibility_note()
        self.progress_status.configure(text=self.state_model.status)
        self.input_error.configure(text=self.state_model.latest_error)
        if self.state_model.latest_error:
            self.input_error.pack(fill="x", pady=(7, 0), after=self.progress_status)
        else:
            self.input_error.pack_forget()
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
            background="#2365d9", foreground=theme.TEXT,
        )
        for name, variable in self._checks.items():
            variable.set(bool(getattr(self.state_model, name)))
        self._sync_microphone_controls()
        self._sync_model_controls()
        if self.input_reset_button is not None:
            self.input_reset_button.configure(
                state="normal" if self._can_change_microphone() else "disabled")
        if self.subtitles_status is not None:
            path = self.state_model.srt_path
            error = self.state_model.srt_error
            text = error or ("Subtitles are saved automatically (SRT)." if path else "SRT recording starts with the next session.")
            self.subtitles_status.config(
                text=text, foreground=theme.ERROR if error else theme.MUTED,
            )
        from .i18n import translate, translate_widgets
        self.window.title(translate("Subtitle settings", self.state_model.ui_language))
        translate_widgets(self.window, self.state_model.ui_language)

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
        window = self.window
        rect = (window.winfo_x(), window.winfo_y(), window.winfo_width(), window.winfo_height())
        fitted = window_placement(window, self.root, rect, framed=True)
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
