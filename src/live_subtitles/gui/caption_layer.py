"""A separately translucent, owned Windows text surface for the Tk overlay."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Callable, Sequence


COLOR_KEY = "#010101"


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
        self._identity: tuple[int, int] | None = None

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
        self._identity = (hwnd, owner)

    def detach(self, window: Any) -> None:
        # Tk can replace the main wrapper during borderless changes. An owned
        # popup must not remain attached to the HWND about to be destroyed.
        hwnd = self.wrapper(window)
        ctypes.set_last_error(0)
        if not self.set_owner(hwnd, -8, 0) and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        self._identity = None

    def visible(self, window: Any) -> bool:
        return bool(self.is_visible(self.wrapper(window)))

    def topmost(self, window: Any) -> bool:
        # Tk 8.6's single-attribute GET for -topmost calls SetWindowPos too.
        # Reading native flags avoids raising the owner on every Configure.
        return bool(self.get_style(self.wrapper(window), -20) & 0x0008)

    def ensure_above_owner(self, window: Any, root: Any) -> None:
        hwnd, owner = self.wrapper(window), self.wrapper(root)
        previous = self.get_owner(owner, 3)  # GW_HWNDPREV: next higher window
        cursor = previous
        # Keep normal owned dialogs (Settings) above the text, including when
        # text is remapped after Clear or the first subtitle of a new session.
        lowest_dialog = None
        while cursor:
            if cursor == hwnd:
                if lowest_dialog is None:
                    return
                previous = lowest_dialog
                break
            if (lowest_dialog is None and self.get_owner(cursor, 4) == owner
                    and self.is_visible(cursor)):
                lowest_dialog = cursor
            cursor = self.get_owner(cursor, 3)
        # Tk's lift(relative) swaps *both* windows on Windows. Swapping an
        # owned popup and its owner creates a Configure/raise feedback loop.
        # Move only the caption, preserving other owned windows above it.
        flags = 0x0001 | 0x0002 | 0x0010 | 0x0200  # NOSIZE, NOMOVE, NOACTIVATE, NOOWNERZORDER
        if not self.set_position(hwnd, previous, 0, 0, 0, 0, flags):
            raise ctypes.WinError(ctypes.get_last_error())


class CaptionLayer:
    """Mirror text above a background window with an independent real alpha.

    Color-key pixels reveal the parent or desktop. Near-black avoids a bright
    color fringe on Tk's antialiased glyph edges; exact black remains available
    for outlines. Windows makes fully transparent pixels pass mouse input on.
    """

    def __init__(self, root: Any, anchor: Any, *, tk_module: Any) -> None:
        self.root, self.anchor, self.tk = root, anchor, tk_module
        self.window: Any | None = None
        self.canvas: Any | None = None
        self._native = _WindowOwner()
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._specs: tuple[dict[str, Any], ...] = ()
        self._opacity = 1.0
        self._signature: tuple[object, ...] | None = None
        self._geometry = ""
        self._topmost: bool | None = None
        self._closed = False
        self._suspended = False
        self._syncing = False
        self._groups: list[list[tuple[int, float, float]]] = []

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
        self.window.configure(background=COLOR_KEY)
        self.window.attributes("-transparentcolor", COLOR_KEY)
        self.window.attributes("-alpha", self._opacity)
        self.canvas = self.tk.Canvas(
            self.window, background=COLOR_KEY, highlightthickness=0,
            borderwidth=0, width=1, height=1,
        )
        self.canvas.pack(fill="both", expand=True)
        self._geometry = ""
        self._topmost = None
        self._signature = None
        self.set_pointer_handlers(self._handlers)
        self._paint()

    def render(self, specs: Sequence[dict[str, Any]], *, opacity: float) -> None:
        self._specs = tuple(dict(spec) for spec in specs)
        opacity = min(1.0, max(0.0, float(opacity)))
        if opacity != self._opacity:
            self._opacity = opacity
            if self._exists():
                self.window.attributes("-alpha", opacity)
        self._paint()
        self.sync_window()

    def _paint(self) -> None:
        if not self._exists():
            return
        signature = tuple(tuple(sorted(spec.items())) for spec in self._specs)
        if signature == self._signature:
            return
        self._signature = signature
        self.canvas.delete("all")
        self._groups.clear()
        for spec in self._specs:
            group = []
            options = dict(spec)
            x, y = options.pop("x"), options.pop("y")
            outline = options.pop("outline", False)
            if outline:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx or dy:
                            item = self.canvas.create_text(
                                x + dx, y + dy, **dict(options, fill="black"),
                            )
                            group.append((item, x + dx, y + dy))
            item = self.canvas.create_text(x, y, **options)
            group.append((item, x, y))
            self._groups.append(group)

    def move_offsets(self, offsets: Sequence[float]) -> None:
        if not self._exists():
            return
        for group, offset in zip(self._groups, offsets):
            for item, x, y in group:
                self.canvas.coords(item, x - offset, y)

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
        if not self.anchor.winfo_ismapped() or not self._specs:
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
            self.window.deiconify()
            self.window.update_idletasks()
        self._native.attach(self.window, self.root)
        self._native.ensure_above_owner(self.window, self.root)

    def hide_window(self) -> None:
        if self._exists() and self.window.state() != "withdrawn":
            self.window.withdraw()

    def prepare_window_change(self) -> None:
        self._suspended = True
        if self._exists():
            self._native.detach(self.window)
            self.hide_window()

    def close(self) -> None:
        self._closed = True
        if self._exists():
            try:
                self.window.destroy()
            except self.tk.TclError:
                pass
        self.window = self.canvas = None
