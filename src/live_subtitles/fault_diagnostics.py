"""Best-effort crash and stall stacks; never capture frame locals or audio."""
from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from typing import BinaryIO

from .diagnostic_logging import diagnostic_logger
from .runtime_paths import log_directory

_sink: BinaryIO | None = None


def enable_fault_diagnostics(role: str) -> None:
    global _sink
    if _sink is not None:
        return
    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    # Separate process files: never rotate/close a handle underneath a signal
    # handler. Native output can include source paths, but never frame locals.
    path = directory / f"fault-{role}-{os.getpid()}.log"
    _sink = path.open("ab", buffering=0)
    _sink.write(f"role={role} pid={os.getpid()} parent={os.getppid()}\n".encode())
    faulthandler.enable(file=_sink, all_threads=True)
    diagnostic_logger().info("Native fault capture enabled; file=%s", path.name)


def arm_gui_watchdog() -> None:
    if _sink is not None:
        faulthandler.dump_traceback_later(15, repeat=False, file=_sink, exit=False)


def close_fault_diagnostics() -> None:
    global _sink
    if _sink is None:
        return
    faulthandler.cancel_dump_traceback_later()
    faulthandler.disable()
    _sink.close()
    _sink = None


def dump_threads() -> None:
    logger = diagnostic_logger()
    for ident, frame in sys._current_frames().items():
        # Stack function/line locations only. No source line or local values.
        frames = traceback.extract_stack(frame)
        locations = "\n".join(f"{f.filename}:{f.lineno} in {f.name}" for f in frames)
        logger.info("Requested thread diagnostic; thread_id=%s\n%s", ident, locations)
