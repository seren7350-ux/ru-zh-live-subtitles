"""One subtitle per language, fitted vertically and animated only on overflow."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .state import SubtitleEntry


def single_line_text(text: str) -> str:
    """Keep complete text while removing embedded line and paragraph breaks."""

    return " ".join(text.split())


@dataclass
class _Line:
    item: int
    origin_x: float
    origin_y: float
    overflow: float


class SingleLineSubtitleView:
    """Canvas text never wraps; each language moves only when it overflows."""

    PADDING = 6
    GAP = 4
    SPEED = 42.0
    PAUSE = 1.2
    FRAME_MS = 33

    def __init__(
        self,
        parent: Any,
        *,
        tk_module: Any,
        on_width_changed: Callable[[int], None] | None = None,
        on_minimum_height: Callable[[int], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.tk = tk_module
        self._clock = clock
        self._on_width_changed = on_width_changed
        self._on_minimum_height = on_minimum_height
        self.container = tk_module.Frame(parent, background="#111318")
        self.canvas = tk_module.Canvas(
            self.container, background="#111318", highlightthickness=0,
            borderwidth=0, width=1, height=1,
        )
        self.canvas.pack(fill="both", expand=True)
        self._layer = None
        if sys.platform == "win32" and hasattr(tk_module, "Toplevel"):
            from .caption_layer import CaptionLayer

            self._layer = CaptionLayer(self.canvas.winfo_toplevel(), self.canvas, tk_module=tk_module)
        self._items = (
            self.canvas.create_text(0, 0, anchor="nw", fill="#d8dbe2", width=0),
            self.canvas.create_text(0, 0, anchor="nw", fill="#ffffff", width=0),
        )
        self._texts = ("", "")
        self._requested_sizes = (20, 34)
        self.effective_russian_font_size = 20
        self.effective_chinese_font_size = 34
        self._show_russian = True
        self._text_opacity = 1.0
        self._text_outline = False
        self._outline_items: list[int] = []
        self._outline_groups: dict[int, list[tuple[int, int, int]]] = {}
        self._signature: tuple[object, ...] | None = None
        self._size = (0, 0)
        self._lines: list[_Line] = []
        self._destroyed = False
        self._timer: str | None = None
        self._started_at = 0.0
        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Destroy>", self._on_destroy)
        if self._layer is not None:
            from .windows_taskbar import bind_window_lifecycle

            # Native restoration maps descendants after the root's lifecycle
            # callbacks; an unchanged canvas size would otherwise miss it.
            bind_window_lifecycle(self.canvas, "<Map>", lambda _event: self.sync_window())

    def _on_destroy(self, event: Any) -> None:
        if event.widget is self.canvas:
            self._destroyed = True
            self._cancel_animation()
            if self._layer is not None:
                self._layer.close()

    def _cancel_animation(self) -> None:
        if self._timer is not None:
            try:
                self.canvas.after_cancel(self._timer)
            except self.tk.TclError:
                pass
            self._timer = None

    def set_pointer_handlers(self, handlers: dict[str, Callable[..., Any]]) -> None:
        if self._layer is not None:
            self._layer.set_pointer_handlers(handlers)

    def sync_window(self) -> None:
        if self._layer is not None and not self._destroyed:
            self._layer.sync_window(resume=True)

    def prepare_window_change(self) -> None:
        if self._layer is not None and not self._destroyed:
            self._layer.prepare_window_change()

    def _on_configure(self, event: Any) -> bool:
        size = (max(1, int(event.width)), max(1, int(event.height)))
        if size == self._size:
            return False
        self._size = size
        if self._on_width_changed is not None:
            self._on_width_changed(max(1, size[0] - self.PADDING * 2))
        self._layout()
        return True

    def render_entries(
        self,
        entries: Sequence[SubtitleEntry],
        *,
        show_russian: bool,
        russian_font_size: int,
        chinese_font_size: int,
        text_opacity: float = 1.0,
        text_outline: bool = False,
    ) -> bool:
        latest = entries[-1] if entries else None
        texts = (
            single_line_text(latest.russian_text) if latest is not None else "",
            single_line_text(latest.chinese_text) if latest is not None else "",
        )
        signature = (
            latest.index if latest is not None else None, texts, show_russian,
            int(russian_font_size), int(chinese_font_size),
            float(text_opacity), bool(text_outline),
        )
        if signature == self._signature:
            return False
        self._signature = signature
        self._texts = texts
        self._show_russian = show_russian
        self._text_opacity = min(1.0, max(0.0, float(text_opacity)))
        self._text_outline = bool(text_outline)
        self._requested_sizes = (int(russian_font_size), int(chinese_font_size))
        self._layout()
        return True

    def _measure(self, sizes: tuple[int, int]) -> list[tuple[int, tuple[int, int, int, int]]]:
        measured = []
        fonts = (("Segoe UI", sizes[0]), ("Microsoft YaHei UI", sizes[1], "bold"))
        for index, item in enumerate(self._items):
            visible = bool(self._texts[index]) and (index == 1 or self._show_russian)
            self.canvas.itemconfigure(
                item, text=self._texts[index], font=fonts[index],
                state="normal" if visible else "hidden", width=0,
                fill="#111318" if self._layer is not None else ("#d8dbe2", "#ffffff")[index],
            )
            self.canvas.coords(item, 0, 0)
            if visible:
                bounds = self.canvas.bbox(item)
                if bounds is not None:
                    if self._text_outline:
                        bounds = (bounds[0] - 1, bounds[1] - 1, bounds[2] + 1, bounds[3] + 1)
                    measured.append((item, bounds))
        return measured

    def _height(self, measurements: list[tuple[int, tuple[int, int, int, int]]]) -> int:
        return (sum(bounds[3] - bounds[1] for _, bounds in measurements)
                + self.GAP * max(0, len(measurements) - 1) + self.PADDING * 2)

    def _layout(self) -> None:
        if self._destroyed:
            return
        self._cancel_animation()
        self._lines.clear()
        width, height = self._size
        # Real text bounds include font fallback glyphs and the current DPI.
        minimum_sizes = (min(8, self._requested_sizes[0]), min(12, self._requested_sizes[1]))
        minimum_height = self._height(self._measure(minimum_sizes))
        if self._on_minimum_height is not None:
            self._on_minimum_height(minimum_height)
        sizes = self._requested_sizes
        measured = self._measure(sizes)
        while self._height(measured) > height and sizes != minimum_sizes:
            sizes = tuple(max(minimum, value - 1) for value, minimum in zip(sizes, minimum_sizes))
            measured = self._measure(sizes)
        self.effective_russian_font_size, self.effective_chinese_font_size = sizes
        if not measured:
            self._present()
            return
        if width <= self.PADDING * 2 or height < minimum_height:
            # The owner grows its minimum height to fit both complete rows.
            # During the intervening Configure event, never draw half a line.
            for item in self._items:
                self.canvas.itemconfigure(item, state="hidden")
            self._present()
            return
        available_width = width - self.PADDING * 2
        y = (height - self._height(measured)) / 2 + self.PADDING
        for item, bounds in measured:
            text_width = bounds[2] - bounds[0]
            text_height = bounds[3] - bounds[1]
            overflow = max(0, text_width - available_width)
            x = self.PADDING if overflow else (width - text_width) / 2
            line = _Line(item, x - bounds[0], y - bounds[1], overflow)
            self._lines.append(line)
            self.canvas.coords(item, line.origin_x, line.origin_y)
            y += text_height + self.GAP
        self._present()
        self._started_at = self._clock()
        if any(line.overflow for line in self._lines):
            self._timer = self.canvas.after(self.FRAME_MS, self._tick)

    def _present(self) -> None:
        fonts = (("Segoe UI", self.effective_russian_font_size),
                 ("Microsoft YaHei UI", self.effective_chinese_font_size, "bold"))
        specs = []
        for line in self._lines:
            index = self._items.index(line.item)
            specs.append(dict(
                x=line.origin_x, y=line.origin_y, anchor="nw", width=0,
                text=self._texts[index], font=fonts[index],
                fill=("#d8dbe2", "#ffffff")[index], outline=self._text_outline,
            ))
        if self._layer is not None:
            self._layer.render(specs, opacity=self._text_opacity)
            return
        # Other Tk platforms keep a functional opaque view; zero still hides
        # text. Independent partial alpha is supplied by the Windows surface.
        for item in self._outline_items:
            self.canvas.delete(item)
        self._outline_items.clear()
        self._outline_groups.clear()
        if self._text_opacity == 0:
            for item in self._items:
                self.canvas.itemconfigure(item, state="hidden")
        elif self._text_outline:
            for line, spec in zip(self._lines, specs):
                options = dict(spec)
                x, y = options.pop("x"), options.pop("y")
                options.pop("outline")
                options["fill"] = "black"
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx or dy:
                            item = self.canvas.create_text(x + dx, y + dy, **options)
                            self.canvas.tag_lower(item)
                            self._outline_items.append(item)
                            self._outline_groups.setdefault(line.item, []).append((item, dx, dy))

    def _tick(self) -> None:
        self._timer = None
        if self._destroyed:
            return
        elapsed = max(0.0, self._clock() - self._started_at)
        offsets = []
        for line in self._lines:
            offset = 0.0
            if line.overflow:
                travel = line.overflow / self.SPEED
                phase = elapsed % (travel + self.PAUSE * 2)
                offset = min(line.overflow, max(0.0, phase - self.PAUSE) * self.SPEED)
                self.canvas.coords(line.item, line.origin_x - offset, line.origin_y)
                for item, dx, dy in self._outline_groups.get(line.item, ()):
                    self.canvas.coords(item, line.origin_x - offset + dx, line.origin_y + dy)
            offsets.append(offset)
        if self._layer is not None:
            self._layer.move_offsets(offsets)
        if any(line.overflow for line in self._lines):
            self._timer = self.canvas.after(self.FRAME_MS, self._tick)
