"""Pure subtitle overlay state, independent of Tkinter and model runtimes."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


DEFAULT_HISTORY_LINES = 20
DEFAULT_DISPLAY_LINES = 1
DEFAULT_OPACITY = 0.88
DEFAULT_CHINESE_FONT_SIZE = 34
DEFAULT_RUSSIAN_FONT_SIZE = 20
DEFAULT_RUSSIAN_COLOR = "#d8dbe2"
DEFAULT_CHINESE_COLOR = "#ffffff"
DEFAULT_OUTLINE_COLOR = "#000000"
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
        background_opacity: float | None = None,
        text_opacity: float = 1.0,
        text_outline: bool = False,
        text_color: str | None = None,
        outline_color: str = DEFAULT_OUTLINE_COLOR,
        auto_outline_color: bool = False,
        toolbar_visible: bool = True,
        auto_start: bool = True,
        chinese_font_size: int = DEFAULT_CHINESE_FONT_SIZE,
        russian_font_size: int = DEFAULT_RUSSIAN_FONT_SIZE,
        show_russian: bool = True,
        topmost: bool = True,
        borderless: bool = True,
        position: str = "bottom",
    ) -> None:
        if not 1 <= history_lines <= 100:
            raise ValueError("History lines must be between 1 and 100.")
        if display_lines != 1:
            raise ValueError("Display lines must be 1 (one current bilingual subtitle).")
        if background_opacity is not None:
            opacity = background_opacity
        if not 0.0 <= opacity <= 1.0:
            raise ValueError("Background opacity must be between 0 and 1.")
        if not 0.0 <= text_opacity <= 1.0:
            raise ValueError("Text opacity must be between 0 and 1.")
        if not 16 <= chinese_font_size <= 72:
            raise ValueError("Chinese font size must be between 16 and 72.")
        if not 10 <= russian_font_size <= 48:
            raise ValueError("Russian font size must be between 10 and 48.")
        if position not in POSITION_PRESETS:
            raise ValueError(f"Position must be one of: {', '.join(POSITION_PRESETS)}.")
        self.history_lines = history_lines
        self.ui_language = "en"
        self.display_lines = display_lines
        self.opacity = opacity
        self.text_opacity = text_opacity
        self.text_outline = text_outline
        # An unset text color preserves the two shades used by older preferences.
        self.text_color = text_color
        self.outline_color = outline_color
        self.auto_outline_color = auto_outline_color
        self.toolbar_visible = toolbar_visible
        self.auto_start = auto_start
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
        self.srt_path = ""
        self.srt_error = ""
        self._entries: deque[SubtitleEntry] = deque(maxlen=history_lines)
        self._seen_indices: set[int] = set()

    @property
    def background_opacity(self) -> float:
        return self.opacity

    @background_opacity.setter
    def background_opacity(self, value: float) -> None:
        # Keep the original opacity attribute/CLI alias compatible.
        self.opacity = value

    @property
    def effective_outline_color(self) -> str:
        if not self.auto_outline_color:
            return self.outline_color
        color = self.text_color or DEFAULT_CHINESE_COLOR
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        luminance = sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))
        black_contrast = (luminance + 0.05) / 0.05
        white_contrast = 1.05 / (luminance + 0.05)
        return "#000000" if black_contrast >= white_contrast else "#ffffff"

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
        self.srt_path = ""
        self.srt_error = ""
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
