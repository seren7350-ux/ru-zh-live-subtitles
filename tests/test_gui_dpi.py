"""Check DPI initialization in isolation before any GUI is created."""
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPI API")
def test_dpi_initialization_is_idempotent_and_preserves_awareness():
    result = subprocess.run([sys.executable, "-c", """
import ctypes
from live_subtitles.gui.dpi import configure_dpi
api = ctypes.WinDLL('shcore')
def current():
    value = ctypes.c_int(-1)
    assert api.GetProcessDpiAwareness(None, ctypes.byref(value)) == 0
    return value.value
before = current()
configure_dpi()
after = current()
assert after == (before if before else 1), (before, after)
configure_dpi()
assert current() == after
"""], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
