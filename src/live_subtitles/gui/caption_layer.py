"""A separately translucent, owned Windows text surface for the Tk overlay."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Callable, Sequence

from .caption_bitmap import CaptionBitmap


class _WindowOwner:
    """Tk override-redirect windows need an explicit native owner on Windows."""

    def __init__(self) -> None:
        api = ctypes.WinDLL("user32", use_last_error=True)
        self.ancestor = api.GetAncestor
        self.ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.ancestor.restype = wintypes.HWND
        self.get_style = api.GetWindowLongW
        self.get_style.argtypes = (wintypes.HWND, ctypes.c_int)
        self.get_style.restype = wintypes.LONG
        self.is_visible = api.IsWindowVisible
        self.is_visible.argtypes = (wintypes.HWND,)
        self.is_visible.restype = wintypes.BOOL
        self.get_owner = api.GetWindow
        self.get_owner.argtypes = (wintypes.HWND, wintypes.UINT)
        self.get_owner.restype = wintypes.HWND
        self.set_style = api.SetWindowLongW
        self.set_style.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.LONG)
        self.set_style.restype = wintypes.LONG
        self.set_owner = api.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else api.SetWindowLongW
        self.set_owner.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        self.set_owner.restype = ctypes.c_ssize_t
        self.set_position = api.SetWindowPos
        self.set_position.argtypes = (
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        )
        self.set_position.restype = wintypes.BOOL

    def wrapper(self, widget: Any) -> int:
        content = widget.winfo_id()
        hwnd = self.ancestor(content, 2)  # GA_ROOT
        if not hwnd or hwnd == content:
            raise OSError("Caption window is not mapped yet.")
        return int(hwnd)

    def attach(self, window: Any, root: Any) -> None:
        hwnd, owner = self.wrapper(window), self.wrapper(root)
        window_style = self.get_style(hwnd, -16)
        if window_style & 0x40000000 or not window_style & 0x80000000:
            raise RuntimeError("Caption surface must be a top-level popup, not a child window.")
        # A helper must never add a taskbar entry or become a foreground window.
        style = self.get_style(hwnd, -20)
        wanted = (style | 0x80 | 0x08000000) & ~0x40000  # TOOLWINDOW | NOACTIVATE, no APPWINDOW
        # Tk can reset native ownership/styles during mapping without replacing
        # either handle; inspect the actual state rather than caching identities.
        if style != wanted:
            ctypes.set_last_error(0)
            if not self.set_style(hwnd, -20, wanted) and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
        if self.get_owner(hwnd, 4) != owner:  # GW_OWNER
            ctypes.set_last_error(0)
            if not self.set_owner(hwnd, -8, owner) and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())

    def layered_handle(self, window: Any) -> int:
        hwnd = self.wrapper(window)
        style = self.get_style(hwnd, -20)
        if not style & 0x80000:  # WS_EX_LAYERED
            ctypes.set_last_error(0)
            if not self.set_style(hwnd, -20, style | 0x80000) and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
        return hwnd

    def visible(self, window: Any) -> bool:
        return bool(self.is_visible(self.wrapper(window)))

    def topmost(self, window: Any) -> bool:
        # Tk 8.6's single-attribute GET for -topmost calls SetWindowPos too.
        # Reading native flags avoids raising the owner on every Configure.
        return bool(self.get_style(self.wrapper(window), -20) & 0x0008)

    def ensure_above_owner(self, window: Any, root: Any, *, behind: Any = None) -> None:
        hwnd, owner = self.wrapper(window), self.wrapper(root)
        previous = self.get_owner(owner, 3)  # GW_HWNDPREV: next higher window
        if behind is not None and previous == self.wrapper(behind):
            previous = self.get_owner(previous, 3)
        if previous == hwnd:
            return
        if previous and not self.topmost(root) and self.get_style(previous, -20) & 0x0008:
            previous = -2  # HWND_NOTOPMOST keeps the caption in the owner's band.
        # Keep the caption next to its owner when another app covers them.
        # Tk's relative lift swaps both windows, so move only the caption.
        flags = 0x0001 | 0x0002 | 0x0010 | 0x0200  # NOSIZE, NOMOVE, NOACTIVATE, NOOWNERZORDER
        if not self.set_position(hwnd, previous, 0, 0, 0, 0, flags):
            raise ctypes.WinError(ctypes.get_last_error())


class CaptionLayer:
    """Own the alpha-composited caption or its invisible mouse hit surface."""

    def __init__(self, root: Any, anchor: Any, *, tk_module: Any, hit_only: bool = False) -> None:
        self.root, self.anchor, self.tk = root, anchor, tk_module
        self._hit_only = hit_only
        self._hit_enabled = False
        self.hit_surface: CaptionLayer | None = None
        self.window: Any | None = None
        self._bitmap: CaptionBitmap | None = None
        self._native = _WindowOwner()
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._specs: tuple[dict[str, Any], ...] = ()
        # Windows skips hit testing at alpha zero. The hit surface covers only
        # the subtitle canvas and uses the smallest nonzero Windows alpha.
        self._opacity = 1 / 255 if hit_only else 1.0
        self._offsets: tuple[int, ...] = ()
        self._painted_size: tuple[int, int] | None = None
        self._geometry = ""
        self._topmost: bool | None = None
        self._closed = False
        self._suspended = False
        self._syncing = False

    def set_pointer_handlers(self, handlers: dict[str, Callable[..., Any]]) -> None:
        self._handlers = dict(handlers)
        if self.window is not None:
            for sequence, callback in self._handlers.items():
                self.window.bind(sequence, callback)

    def _exists(self) -> bool:
        try:
            return self.window is not None and bool(self.window.winfo_exists())
        except self.tk.TclError:
            return False

    def _create(self) -> None:
        self.window = self.tk.Toplevel(self.root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        # On Windows, Tk combines override-redirect + transient into WS_CHILD
        # (with the desktop as parent), rather than an owned WS_POPUP. Setting
        # GWLP_HWNDPARENT on that child then reparents it: screen coordinates
        # become parent-relative and raise/configure events feed each other.
        # Keep a real popup and establish ownership only through _WindowOwner.
        if self._hit_only:
            self.window.configure(background="#010101")
            self.window.attributes("-alpha", self._opacity)
        self._geometry = ""
        self._topmost = None
        self._painted_size = None
        self.set_pointer_handlers(self._handlers)

    def set_hit_enabled(self, enabled: bool) -> None:
        if enabled != self._hit_enabled:
            self._hit_enabled = enabled
            self.sync_window()

    def render(self, specs: Sequence[dict[str, Any]], *, opacity: float) -> None:
        specs = tuple(dict(spec) for spec in specs)
        if specs != self._specs:
            self._specs = specs
            self._offsets = (0,) * len(specs)
            self._painted_size = None
        opacity = min(1.0, max(0.0, float(opacity)))
        if opacity != self._opacity:
            self._opacity = opacity
            self._painted_size = None
        self.sync_window()

    def _paint(self, size: tuple[int, int]) -> None:
        if self._hit_only or size == self._painted_size:
            return
        if self._bitmap is None:
            self._bitmap = CaptionBitmap()
        hwnd = self._native.layered_handle(self.window)
        self._bitmap.paint(hwnd, size, self._specs, self._offsets, self._opacity, self.anchor)
        self._painted_size = size

    def move_offsets(self, offsets: Sequence[float]) -> None:
        pixels = tuple(round(offset) for offset in offsets)
        if pixels != self._offsets:
            self._offsets = pixels
            self._painted_size = None
            if self._exists() and not self._suspended and self.window.state() == "normal":
                self._paint((self.anchor.winfo_width(), self.anchor.winfo_height()))

    def sync_window(self, *, resume: bool = False) -> None:
        if self._closed or self._syncing:
            return
        if resume:
            self._suspended = False
        if self._suspended:
            return
        self._syncing = True
        try:
            self._sync_window()
        finally:
            self._syncing = False

    def _sync_window(self) -> None:
        if not self.root.winfo_ismapped() or self.root.state() in {"withdrawn", "iconic"}:
            self.hide_window()
            return
        has_content = self._hit_enabled if self._hit_only else bool(self._specs)
        if not self.anchor.winfo_ismapped() or not has_content:
            self.hide_window()
            return
        if not self._exists():
            self._create()
        width, height = self.anchor.winfo_width(), self.anchor.winfo_height()
        if width <= 1 or height <= 1:
            self.hide_window()
            return
        # Tk's bare negative offset measures from the opposite screen edge.
        # '+-N' retains an absolute negative virtual-desktop coordinate.
        geometry = f"{width}x{height}+{self.anchor.winfo_rootx()}+{self.anchor.winfo_rooty()}"
        if geometry != self._geometry:
            self.window.geometry(geometry)
            self._geometry = geometry
        topmost = self._native.topmost(self.root)
        if topmost != self._topmost:
            self.window.attributes("-topmost", topmost)
            self._topmost = topmost
        if self.window.state() == "withdrawn" or not self._native.visible(self.window):
            # Windows can hide an owned popup while keeping Tk's state normal
            # when the owner is minimized. Remap through Tcl so it reappears.
            self.window.withdraw()
            self.window.update_idletasks()
            # Install NOACTIVATE and ownership before exposing the popup.
            self._native.attach(self.window, self.root)
            self._painted_size = None
            self._paint((width, height))
            self.window.state("normal")
            self.window.update_idletasks()
        self._native.attach(self.window, self.root)
        self._paint((width, height))
        if (self.hit_surface is not None and self.hit_surface._exists()
                and self.hit_surface.window.state() == "normal"):
            self._native.ensure_above_owner(self.window, self.root, behind=self.hit_surface.window)
        else:
            self._native.ensure_above_owner(self.window, self.root)

    def hide_window(self) -> None:
        if self._exists() and self.window.state() != "withdrawn":
            self.window.withdraw()

    def prepare_window_change(self) -> None:
        self._suspended = True
        # Discard the popup before Tk changes the owner wrapper. Reusing the
        # Tcl window can leave an HWND invalidated by the native owner change.
        self._destroy_popup()

    def _destroy_popup(self) -> None:
        if self._exists():
            self.window.destroy()
        self.window = None

    def close(self) -> None:
        self._closed = True
        try:
            self._destroy_popup()
        finally:
            if self._bitmap is not None:
                self._bitmap.close()
                self._bitmap = None
