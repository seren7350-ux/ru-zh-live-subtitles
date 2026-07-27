"""Pure subtitle overlay state, independent of Tkinter and model runtimes."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


DEFAULT_HISTORY_LINES = 20
DEFAULT_DISPLAY_LINES = 2
DEFAULT_OPACITY = 0.88
DEFAULT_CHINESE_FONT_SIZE = 34
DEFAULT_RUSSIAN_FONT_SIZE = 20
POSITION_PRESETS = ("top", "bottom", "floating")


@dataclass(frozen=True)
class SubtitleEntry:
    index: int
    russian_text: str
    chinese_text: str
    received_at: float
    russian_latency_seconds: float | None
    chinese_latency_seconds: float | None
    succeeded: bool = True
    error: str | None = None


class SubtitleViewState:
    """Bounded history and user-visible settings for one overlay window."""

    def __init__(
        self,
        *,
        history_lines: int = DEFAULT_HISTORY_LINES,
        display_lines: int = DEFAULT_DISPLAY_LINES,
        opacity: float = DEFAULT_OPACITY,
        chinese_font_size: int = DEFAULT_CHINESE_FONT_SIZE,
        russian_font_size: int = DEFAULT_RUSSIAN_FONT_SIZE,
        show_russian: bool = True,
        topmost: bool = True,
        borderless: bool = True,
        position: str = "bottom",
    ) -> None:
        if not 1 <= history_lines <= 100:
            raise ValueError("History lines must be between 1 and 100.")
        if not 1 <= display_lines <= 5:
            raise ValueError("Display lines must be between 1 and 5.")
        if not 0.5 <= opacity <= 1.0:
            raise ValueError("Opacity must be between 0.5 and 1.0.")
        if not 16 <= chinese_font_size <= 72:
            raise ValueError("Chinese font size must be between 16 and 72.")
        if not 10 <= russian_font_size <= 48:
            raise ValueError("Russian font size must be between 10 and 48.")
        if position not in POSITION_PRESETS:
            raise ValueError(f"Position must be one of: {', '.join(POSITION_PRESETS)}.")
        self.history_lines = history_lines
        self.display_lines = display_lines
        self.opacity = opacity
        self.chinese_font_size = chinese_font_size
        self.russian_font_size = russian_font_size
        self.show_russian = show_russian
        self.topmost = topmost
        self.borderless = borderless
        self.position = position
        self.status = "Ready"
        self.settings_visible = False
        self.listening = False
        self.preparing = False
        self.stopping = False
        self.latest_error = ""
        self._entries: deque[SubtitleEntry] = deque(maxlen=history_lines)
        self._seen_indices: set[int] = set()

    @property
    def entries(self) -> tuple[SubtitleEntry, ...]:
        return tuple(self._entries)

    @property
    def visible_entries(self) -> tuple[SubtitleEntry, ...]:
        return tuple(self._entries)[-self.display_lines :]

    def begin_session(self) -> None:
        self.status = "Preparing models..."
        self.preparing = True
        self.listening = False
        self.stopping = False
        self.latest_error = ""
        self._entries.clear()
        self._seen_indices.clear()

    def add_subtitle(self, entry: SubtitleEntry) -> bool:
        if entry.index in self._seen_indices:
            return False
        self._seen_indices.add(entry.index)
        self._entries.append(entry)
        self.latest_error = ""
        return True

    def set_segment_error(self, message: str) -> None:
        self.latest_error = message

    def set_status(self, status: str) -> None:
        self.status = status
        self.preparing = status.startswith("Preparing") or status == "Models ready"
        self.listening = status.startswith("Listening")
        self.stopping = status.startswith("Stopping")

    def clear(self) -> None:
        self._entries.clear()
        self.latest_error = ""

    def set_position(self, position: str) -> None:
        if position not in POSITION_PRESETS:
            raise ValueError(f"Position must be one of: {', '.join(POSITION_PRESETS)}.")
        self.position = position
