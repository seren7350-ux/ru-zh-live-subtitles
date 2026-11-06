"""Incremental UTF-8 SRT output using offsets on the captured audio timeline."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4


def _milliseconds(seconds: float | None) -> int:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("SRT audio timestamps must be finite and nonnegative.")
    # Decimal avoids floating-point artifacts at a millisecond rollover.
    return int((Decimal(str(seconds)) * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def _timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1000)
    minutes, secs = divmod(seconds, 60)
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"


class SrtSession:
    """One output file per Start; one caller owns a session on the GUI thread.

    Each append closes its file before returning, so already written captions
    survive an engine or application process exit. This does not promise
    durability against power loss or a filesystem failure.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen_indices: set[int] = set()
        self._cue_count = 0
        self._length = 0
        self._failed = False

    @classmethod
    def create(cls, directory: Path) -> SrtSession:
        directory = Path(directory).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        directory = directory.resolve(strict=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = directory / f"subtitles-{stamp}-{uuid4().hex}.srt"
        # Exclusive creation never replaces an earlier session or user file.
        with path.open("xb"):
            pass
        return cls(path.resolve(strict=True))

    def append(
        self,
        index: int,
        start_seconds: float | None,
        end_seconds: float | None,
        russian_text: str,
        chinese_text: str,
    ) -> bool:
        if self._failed:
            raise OSError("SRT output is unavailable after a previous write failure.")
        if index in self._seen_indices:
            return False
        start = _milliseconds(start_seconds)
        end = _milliseconds(end_seconds)
        if end <= start:
            raise ValueError("SRT audio end must be later than start at millisecond precision.")
        lines = [" ".join(text.split()) for text in (russian_text, chinese_text)]
        text = "\n".join(line for line in lines if line)
        if not text:
            raise ValueError("SRT cues require nonempty subtitle text.")
        cue = (
            f"{self._cue_count + 1}\n{_timestamp(start)} --> {_timestamp(end)}\n"
            f"{text}\n\n"
        ).encode("utf-8")
        try:
            with self.path.open("r+b", buffering=0) as stream:
                if stream.seek(0, 2) != self._length:
                    raise OSError("SRT file changed outside this subtitle session.")
                try:
                    view = memoryview(cue)
                    while view:
                        written = stream.write(view)
                        if not written:
                            raise OSError("SRT write did not make progress.")
                        view = view[written:]
                    stream.flush()
                except OSError:
                    # Roll back a partial cue when the filesystem still allows
                    # it. Never alter a previously completed cue.
                    try:
                        stream.truncate(self._length)
                    except OSError:
                        pass
                    raise
        except OSError:
            self._failed = True
            raise
        self._length += len(cue)
        self._cue_count += 1
        self._seen_indices.add(index)
        return True
