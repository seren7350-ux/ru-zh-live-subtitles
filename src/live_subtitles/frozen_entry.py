"""Dispatch the shared CLI safely from console and windowed frozen launchers."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .diagnostic_logging import (
    configure_diagnostic_logging,
    safe_text_stream,
)
from .runtime_paths import application_executable, is_frozen

CONSOLE_EXECUTABLE = "ru-zh-subtitles-console"
WINDOWED_EXECUTABLE = "ru-zh-subtitles"
DEVELOPMENT_LAUNCH_MODE = "RU_ZH_LAUNCH_MODE"


def launch_mode(executable: Path | None = None) -> str:
    """Return ``console`` or ``windowed`` without importing application-heavy modules."""

    if not is_frozen():
        override = os.environ.get(DEVELOPMENT_LAUNCH_MODE, "").lower()
        if override in {"console", "windowed"}:
            return override
    stem = (executable or application_executable()).stem.lower()
    return "console" if stem == CONSOLE_EXECUTABLE else "windowed"


def default_arguments(mode: str) -> list[str]:
    """Return the no-argument behavior for a frozen launcher."""

    if mode == "console":
        return ["--help"]
    return [
        "live-overlay",
        "--translation-device",
        "cpu",
        "--offline",
        "--no-auto-start",
    ]


def run_frozen(
    argv: Sequence[str] | None = None,
    *,
    executable: Path | None = None,
) -> int:
    """Run the existing CLI after applying the selected launcher's small policy."""

    mode = launch_mode(executable)
    logger: logging.Logger | None = None
    if mode == "windowed":
        # PyInstaller's noconsole bootloader and pythonw both expose None streams.
        # A sink protects argparse and existing terminal summaries without putting
        # any recognized/translated subtitle text into the diagnostic log.
        sys.stdin = safe_text_stream(sys.stdin)
        sys.stdout = safe_text_stream(sys.stdout)
        sys.stderr = safe_text_stream(sys.stderr)
        logger = configure_diagnostic_logging()
        logger.info("Application startup; version=%s; mode=windowed", __version__)

    effective_arguments = list(sys.argv[1:] if argv is None else argv)
    if not effective_arguments:
        effective_arguments = default_arguments(mode)

    # This import intentionally follows multiprocessing.freeze_support() in the
    # tiny packaging/entrypoint.py script.
    from .cli import main as cli_main

    try:
        result = int(cli_main(effective_arguments))
    except SystemExit as exc:
        result = int(exc.code or 0)
        if logger is not None and result:
            logger.warning("Command-line parsing failed; exit_code=%s", result)
    except BaseException as exc:
        if logger is not None:
            # Log only the exception class: exception text can contain a path,
            # microphone name, user text, or other data not suitable for logs.
            logger.error("Unhandled launcher failure; type=%s", type(exc).__name__)
        raise
    finally:
        if logger is not None:
            logger.info("Application exit")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Public frozen dispatcher used by the packaging script and tests."""

    return run_frozen(argv)
