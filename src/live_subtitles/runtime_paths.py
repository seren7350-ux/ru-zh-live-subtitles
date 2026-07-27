"""Paths that keep bundled resources separate from per-user writable data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APPLICATION_DIRECTORY_NAME = "ru-zh-live-subtitles"


def is_frozen() -> bool:
    """Return whether the process is running from a PyInstaller bundle."""

    return bool(getattr(sys, "frozen", False))


def application_executable() -> Path:
    """Return the interpreter in source mode and the EXE in a frozen process."""

    return Path(sys.executable).resolve()


def bundled_resource_path(relative_path: str | Path) -> Path:
    """Locate a read-only resource bundled by PyInstaller.

    This is deliberately the only application helper that knows about
    ``sys._MEIPASS``. Model caches must use their dedicated per-user helpers.
    """

    if is_frozen():
        bundle_root = Path(getattr(sys, "_MEIPASS"))
    else:
        bundle_root = Path(__file__).resolve().parents[2]
    return (bundle_root / Path(relative_path)).resolve()


def user_data_directory() -> Path:
    """Return the writable, per-user application data directory."""

    if local_app_data := os.environ.get("LOCALAPPDATA"):
        base = Path(local_app_data).expanduser()
    else:
        base = Path.home() / "AppData" / "Local"
    return base / APPLICATION_DIRECTORY_NAME


def log_directory() -> Path:
    """Return the per-user diagnostic log directory without creating it."""

    return user_data_directory() / "logs"
