"""Coordinate native owner changes across the main, caption and settings windows.

Rendering never changes native ownership or taskbar registration. Those changes
belong to explicit activation, mapping, pinning and decoration transitions.
"""
from typing import Any, Callable

from ..diagnostic_logging import diagnostic_logger
from .state import SubtitleViewState


class WindowCoordinator:
    def __init__(self, root: Any, state: SubtitleViewState, *, taskbar: Any,
                 caption: Callable[[], Any], settings: Callable[[], Any],
                 closing: Callable[[], bool]) -> None:
        self.root = root
        self.state = state
        self.taskbar = taskbar
        self.caption = caption
        self.settings = settings
        self.closing = closing
        self.transition_pending = False

    def sync_caption(self) -> None:
        if self.transition_pending:
            return
        sync = getattr(self.caption(), "sync_window", None)
        if callable(sync):
            sync()

    def sync_taskbar(self) -> None:
        if self.taskbar is not None and not self.closing():
            try:
                self.taskbar.ensure_button(self.root)
            except OSError:
                diagnostic_logger().exception("Could not register the subtitle taskbar window")

    def reveal(self) -> None:
        if self.closing():
            return
        if self.root.state() in {"withdrawn", "iconic"}:
            self.root.deiconify()
        if self.taskbar is None:
            self.root.lift()
        else:
            self.sync_taskbar()
            try:
                self.taskbar.activate(self.root)
            except OSError:
                diagnostic_logger().exception("Could not activate the subtitle taskbar window")
        self.sync_caption()
        # Native restoration may finish mapping the owner after this call.
        self.root.after_idle(self.sync_caption)

    def apply_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self.state.topmost))
        self.sync_caption()
        panel = self.settings()
        if panel is not None:
            panel.window.attributes("-topmost", bool(self.state.topmost))

    def begin_decoration_change(self, finished: Callable[[], None]) -> None:
        if self.closing() or self.transition_pending:
            return
        geometry = str(self.root.geometry())
        self.transition_pending = True
        prepare = getattr(self.caption(), "prepare_window_change", None)
        if callable(prepare):
            prepare()
        self.root.overrideredirect(bool(self.state.borderless))
        self.root.after_idle(lambda: self._finish_decoration_change(geometry, finished))

    def _finish_decoration_change(self, geometry: str, finished: Callable[[], None]) -> None:
        if self.closing():
            self.transition_pending = False
            return
        self.root.geometry(geometry)
        self.root.attributes("-topmost", bool(self.state.topmost))
        self.root.attributes("-alpha", float(self.state.opacity))
        # Repeating resizable() here would replace the Windows shell wrapper.
        self.sync_taskbar()
        self.root.configure(cursor="")
        self.transition_pending = False
        self.sync_caption()
        finished()
