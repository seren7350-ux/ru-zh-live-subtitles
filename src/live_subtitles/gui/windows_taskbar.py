"""Keep Tk's actual Windows toplevel accessible through the shell."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from types import SimpleNamespace
from typing import Any, Callable


GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_MINIMIZEBOX = 0x20000
WS_SYSMENU = 0x80000
WS_EX_TOOLWINDOW = 0x80
WS_EX_APPWINDOW = 0x40000
GA_ROOT = 2
# Change visibility/styles without changing size, position, stacking or focus.
KEEP_PLACEMENT = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0200
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
FLASHW_TRAY = 2
SW_RESTORE = 9


def bind_window_lifecycle(root: Any, sequence: str, callback: Callable[[Any], None]) -> None:
    """Defer root lifecycle handlers through Tcl before returning to Python.

    Native user32 calls can dispatch Tk events synchronously, outside an
    _tkinter call. Calling a Python event binding there aborts CPython because
    _tkinter has no saved Tcl thread state (keeping the GIL does not fix it).
    Tcl's after-idle queue returns through _tkinter's normal event boundary.
    """

    if not hasattr(root, "tk"):  # simple headless widget doubles
        root.bind(sequence, callback)
        return

    pending = ""

    def dispatch() -> None:
        root.tk.call("unset", "-nocomplain", pending)
        if root.winfo_exists():
            callback(SimpleNamespace(widget=root))

    command = root.register(dispatch)
    pending = f"::{command}_pending"
    # Only root events matter; discard child bindtag events. Coalesce a burst
    # of geometry notifications into one callback that reads current geometry.
    root.bind(sequence, (
        f'if {{"%W" eq "{root}"}} {{'
        f'if {{[info exists {pending}]}} {{after cancel ${pending}}}; '
        f'set {pending} [after idle [list {command}]]'
        '}'
    ))
    # Tkinter's string-binding branch ignores add=True; Tcl's '+' prefix is
    # required to preserve existing Python destruction/animation cleanup.
    root.bind("<Destroy>", "+" + (
        f'if {{"%W" eq "{root}"}} {{'
        f'if {{[info exists {pending}]}} {{after cancel ${pending}}}; '
        f'unset -nocomplain {pending}'
        '}'
    ))


class _FlashInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
        ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
        ("dwTimeout", wintypes.DWORD),
    ]


class WindowsTaskbar:
    """Used only on Windows, on the Tk thread and on the main window."""

    def __init__(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = wintypes.HWND
        for name, result, arguments in (
            ("GetAncestor", hwnd, (hwnd, wintypes.UINT)),
            ("GetWindowLongW", wintypes.LONG, (hwnd, ctypes.c_int)),
            ("SetWindowLongW", wintypes.LONG, (hwnd, ctypes.c_int, wintypes.LONG)),
            ("IsWindowVisible", wintypes.BOOL, (hwnd,)),
            ("IsIconic", wintypes.BOOL, (hwnd,)),
            ("ShowWindow", wintypes.BOOL, (hwnd, ctypes.c_int)),
            ("SetWindowPos", wintypes.BOOL, (hwnd, hwnd, *([ctypes.c_int] * 4), wintypes.UINT)),
            ("SetForegroundWindow", wintypes.BOOL, (hwnd,)),
            ("FlashWindowEx", wintypes.BOOL, (ctypes.POINTER(_FlashInfo),)),
        ):
            function = getattr(user32, name)
            function.argtypes = arguments
            function.restype = result
        self._user32 = user32

    def wrapper(self, root: Any) -> int:
        # winfo_id is Tk's content HWND. Its shell-facing wrapper can change
        # when Tk toggles overrideredirect; never cache a previous wrapper.
        content = root.winfo_id()
        hwnd = self._user32.GetAncestor(content, GA_ROOT)
        if not hwnd or hwnd == content:
            raise OSError("Tk main window does not have a Windows toplevel wrapper.")
        return hwnd

    def _position(self, hwnd: int, flags: int) -> None:
        if not self._user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, KEEP_PLACEMENT | flags):
            raise ctypes.WinError(ctypes.get_last_error())

    def ensure_button(self, root: Any) -> None:
        hwnd = self.wrapper(root)
        ctypes.set_last_error(0)
        window_style = self._user32.GetWindowLongW(hwnd, GWL_STYLE)
        if not window_style and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        # Explorer only minimizes an active taskbar window when its native
        # styles advertise that capability. Tk removes these for an override-
        # redirect window; restoring them does not add a caption or frame.
        wanted_window_style = window_style | WS_MINIMIZEBOX | WS_SYSMENU
        ctypes.set_last_error(0)
        style = self._user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not style and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        wanted = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        if wanted == style and wanted_window_style == window_style:
            return
        # Let Explorer reevaluate a mapped tool window as an application
        # window. A withdrawn or minimized window must stay in that state.
        remap = bool(style & WS_EX_TOOLWINDOW and self._user32.IsWindowVisible(hwnd)
                     and not self._user32.IsIconic(hwnd))
        if remap:
            self._position(hwnd, SWP_HIDEWINDOW)
        try:
            for index, previous_style, new_style in (
                (GWL_STYLE, window_style, wanted_window_style),
                (GWL_EXSTYLE, style, wanted),
            ):
                if new_style != previous_style:
                    ctypes.set_last_error(0)
                    previous = self._user32.SetWindowLongW(hwnd, index, new_style)
                    if not previous and ctypes.get_last_error():
                        raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._position(hwnd, SWP_FRAMECHANGED | (SWP_SHOWWINDOW if remap else 0))

    def activate(self, root: Any) -> None:
        hwnd = self.wrapper(root)
        # Explorer can minimize the wrapper before Tk receives WM_SIZE.
        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindow(hwnd, SW_RESTORE)
        if not self._user32.SetForegroundWindow(hwnd):
            # Windows may deny foreground activation. Signal the existing
            # taskbar button instead of stealing focus from another program.
            flash = _FlashInfo(ctypes.sizeof(_FlashInfo), hwnd, FLASHW_TRAY, 3, 0)
            self._user32.FlashWindowEx(ctypes.byref(flash))
