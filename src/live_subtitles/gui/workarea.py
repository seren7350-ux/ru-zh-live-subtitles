"""Window placement inside the nearest monitor's usable desktop area."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


def work_area(rect: tuple[int, int, int, int], fallback: tuple[int, int]) -> tuple[int, int, int, int]:
    if os.name != "nt":
        return (0, 0, *fallback)
    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
    api = ctypes.WinDLL("user32", use_last_error=True)
    find = api.MonitorFromRect
    find.argtypes = (ctypes.POINTER(wintypes.RECT), wintypes.DWORD)
    find.restype = wintypes.HANDLE
    info = api.GetMonitorInfoW
    info.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
    info.restype = wintypes.BOOL
    x, y, width, height = rect
    box = wintypes.RECT(x, y, x + width, y + height)
    monitor = find(ctypes.byref(box), 2)  # MONITOR_DEFAULTTONEAREST
    data = MonitorInfo(); data.size = ctypes.sizeof(data)
    if not monitor or not info(monitor, ctypes.byref(data)):
        raise ctypes.WinError(ctypes.get_last_error())
    r = data.work
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def fit_rectangle(rect: tuple[int, int, int, int], area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x, y, width, height = rect
    left, top, available_width, available_height = area
    width, height = min(max(1, width), available_width), min(max(1, height), available_height)
    return (max(left, min(x, left + available_width - width)),
            max(top, min(y, top + available_height - height)), width, height)


def client_placement_area(window: object, area: tuple[int, int, int, int], *, framed: bool) -> tuple[int, int, int, int]:
    """Tk sizes describe the client; placement must also fit its outer frame."""
    if not framed:
        return area
    border = max(0, window.winfo_rootx() - window.winfo_x())
    title = max(0, window.winfo_rooty() - window.winfo_y())
    left, top, width, height = area
    return left, top, max(1, width - 2 * border), max(1, height - title - border)


def positioned(rect: tuple[int, int, int, int], area: tuple[int, int, int, int], preset: str) -> tuple[int, int, int, int]:
    x, y, width, height = fit_rectangle(rect, area)
    left, top, aw, ah = area
    if preset == "top":
        x, y = left + (aw - width) // 2, top + min(20, max(0, ah - height))
    elif preset == "bottom":
        x, y = left + (aw - width) // 2, top + max(0, ah - height - 20)
    return x, y, width, height


def window_placement(window, screen, rect: tuple[int, int, int, int], *,
                     framed: bool, preset: str = "floating") -> tuple[int, int, int, int]:
    """Position a Tk client rectangle within the usable area of its monitor."""
    area = work_area(rect, (screen.winfo_screenwidth(), screen.winfo_screenheight()))
    return positioned(rect, client_placement_area(window, area, framed=framed), preset)
