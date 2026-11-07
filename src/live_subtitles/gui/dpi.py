"""Set DPI awareness before Tk creates any HWNDs."""
import ctypes
import sys

from ..diagnostic_logging import diagnostic_logger


def configure_dpi() -> None:
    if sys.platform != "win32":
        return
    api = ctypes.WinDLL("shcore", use_last_error=True)
    get = api.GetProcessDpiAwareness
    get.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
    get.restype = ctypes.c_long
    set_awareness = api.SetProcessDpiAwareness
    set_awareness.argtypes = (ctypes.c_int,)
    set_awareness.restype = ctypes.c_long
    current = ctypes.c_int()
    if get(None, ctypes.byref(current)) != 0:
        diagnostic_logger().warning("Could not read process DPI awareness")
        return
    if current.value != 0:
        return  # Respect an executable manifest or hosting process.
    # Tk 8.6 does not automatically rescale all custom assets on monitor moves.
    # System awareness removes bitmap scaling on the launch display without
    # claiming support for unimplemented per-monitor layout transitions.
    result = set_awareness(1)
    if result != 0:
        diagnostic_logger().warning("Could not enable system DPI awareness: %s", result)


def scale_factor(window) -> float:
    return max(1.0, window.winfo_fpixels("1i") / 96)
