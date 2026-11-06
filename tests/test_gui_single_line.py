from types import SimpleNamespace

import pytest

from live_subtitles.gui.single_line import SingleLineSubtitleView, single_line_text
from live_subtitles.gui.state import SubtitleEntry


class Canvas:
    def __init__(self, *args, **kwargs):
        self.options = kwargs
        self.items = {}
        self.bindings = {}
        self.timers = {}
        self._timer_number = 0

    def pack(self, **kwargs):
        pass

    def bind(self, event, callback):
        self.bindings[event] = callback

    def create_text(self, x, y, **options):
        item = len(self.items) + 1
        self.items[item] = dict(options, coords=(x, y))
        return item

    def itemconfigure(self, item, **options):
        self.items[item].update(options)

    def delete(self, item):
        self.items.pop(item, None)

    def tag_lower(self, item):
        pass

    def coords(self, item, *coordinates):
        if coordinates:
            self.items[item]['coords'] = coordinates
        return self.items[item]['coords']

    def bbox(self, item):
        options = self.items[item]
        if options.get('state') == 'hidden':
            return None
        size = options['font'][1]
        width = len(options['text']) * size
        x, y = options['coords']
        # Include overhang and line spacing, like Tk's native text bbox.
        return (x - 1, y, x + width + 1, y + size * 2)

    def after(self, milliseconds, callback):
        self._timer_number += 1
        name = f'timer-{self._timer_number}'
        self.timers[name] = callback
        return name

    def after_cancel(self, name):
        self.timers.pop(name, None)

    def tick(self):
        callbacks, self.timers = self.timers, {}
        for callback in callbacks.values():
            callback()


@pytest.fixture
def view():
    minimums = []
    now = [0.0]
    canvas_api = SimpleNamespace(Frame=Canvas, Canvas=Canvas, TclError=RuntimeError)
    result = SingleLineSubtitleView(
        None, tk_module=canvas_api, clock=lambda: now[0],
        on_minimum_height=minimums.append,
    )
    result._on_configure(SimpleNamespace(width=600, height=200))
    result._test_now = now
    return result, minimums


def render(view, ru='Привет', zh='你好', index=1, **kwargs):
    return view.render_entries(
        [SubtitleEntry(index, ru, zh, 0.0, None, None)],
        **dict(show_russian=True, russian_font_size=20, chinese_font_size=34, **kwargs),
    )


def test_normalization_preserves_unicode_without_line_breaks():
    assert single_line_text('  Привет\r\n мир\t你好\u2028世界\u2029! ') == 'Привет мир 你好 世界 !'


def test_only_latest_caption_has_one_item_per_language_without_scrolling(view):
    display, _ = view
    display.render_entries(
        [SubtitleEntry(1, 'old', '旧', 0, None, None),
         SubtitleEntry(2, 'Новая\nстрока', '新的\r\n字幕', 0, None, None)],
        show_russian=True, russian_font_size=20, chinese_font_size=34,
    )
    items = list(display.canvas.items.values())
    assert [item['text'] for item in items] == ['Новая строка', '新的 字幕']
    assert all(item['width'] == 0 for item in items)
    assert 'yscrollcommand' not in display.canvas.options
    assert '<MouseWheel>' not in display.canvas.bindings


def test_fitting_text_stays_centered_without_animation_timer(view):
    display, _ = view
    render(display)
    assert display.canvas.timers == {}
    for line in display._lines:
        left, _, right, _ = display.canvas.bbox(line.item)
        assert (left + right) / 2 == 300
        assert line.overflow == 0


def test_exact_fit_is_static_but_one_pixel_overflow_moves_after_pause(view):
    display, _ = view
    render(display, ru='Я' * 20, zh='')
    exact_width = 20 * 20 + 2 + display.PADDING * 2
    display._on_configure(SimpleNamespace(width=exact_width, height=200))
    assert display.canvas.timers == {}
    display._on_configure(SimpleNamespace(width=exact_width - 1, height=200))
    assert display._lines[0].overflow == 1
    initial = display.canvas.coords(display._items[0])
    display._test_now[0] = display.PAUSE + 0.1
    display.canvas.tick()
    assert display.canvas.coords(display._items[0])[0] == initial[0] - 1
    assert len(display.canvas.timers) == 1


def test_only_overflowing_language_moves_and_unchanged_poll_does_not_reset(view):
    display, _ = view
    render(display, ru='Я' * 50, zh='短')
    russian, chinese = display._lines
    initial_ru = display.canvas.coords(russian.item)
    initial_zh = display.canvas.coords(chinese.item)
    assert display.canvas.bbox(russian.item)[0] == display.PADDING
    assert display.canvas.items[russian.item]['text'] == 'Я' * 50
    display._test_now[0] = display.PAUSE + 0.5
    display.canvas.tick()
    moved = display.canvas.coords(russian.item)
    assert moved[0] == initial_ru[0] - display.SPEED * 0.5
    assert not render(display, ru='Я' * 50, zh='短')
    assert display.canvas.coords(russian.item) == moved
    assert display.canvas.coords(chinese.item) == initial_zh
    assert len(display.canvas.timers) == 1


def test_new_caption_resets_animation_to_start(view):
    display, _ = view
    render(display, ru='Я' * 50)
    display._test_now[0] = 2.0
    display.canvas.tick()
    assert render(display, ru='Н' * 60, index=2)
    assert display.canvas.bbox(display._items[0])[0] == display.PADDING
    assert display.canvas.items[display._items[0]]['text'] == 'Н' * 60
    assert len(display.canvas.timers) == 1


def test_resize_stops_animation_when_text_fits_and_restarts_on_overflow(view):
    display, _ = view
    render(display, ru='Я' * 50)
    display._on_configure(SimpleNamespace(width=1200, height=200))
    left, _, right, _ = display.canvas.bbox(display._items[0])
    assert (left + right) / 2 == 600
    assert display.canvas.timers == {}
    display._on_configure(SimpleNamespace(width=600, height=200))
    assert display.canvas.bbox(display._items[0])[0] == display.PADDING
    initial = display.canvas.coords(display._items[0])
    assert not display._on_configure(SimpleNamespace(width=600, height=200))
    display.canvas.tick()
    assert display.canvas.coords(display._items[0]) == initial
    assert len(display.canvas.timers) == 1


def test_vertical_fit_uses_complete_glyph_bounds_and_restores_requested_sizes(view):
    display, minimums = view
    render(display)
    display._on_configure(SimpleNamespace(width=600, height=65))
    assert display.effective_russian_font_size < 20
    assert display.effective_chinese_font_size < 34
    for line in display._lines:
        _, top, _, bottom = display.canvas.bbox(line.item)
        assert 0 <= top < bottom <= 65
    assert minimums[-1] == 8 * 2 + 12 * 2 + display.GAP + display.PADDING * 2
    display._on_configure(SimpleNamespace(width=600, height=200))
    assert (display.effective_russian_font_size, display.effective_chinese_font_size) == (20, 34)


def test_transient_too_small_view_hides_whole_rows_until_minimum_is_restored(view):
    display, minimums = view
    render(display)
    display._on_configure(SimpleNamespace(width=600, height=20))
    assert minimums[-1] > 20
    assert all(item['state'] == 'hidden' for item in display.canvas.items.values())
    display._on_configure(SimpleNamespace(width=600, height=minimums[-1]))
    assert len(display._lines) == 2
    assert all(item['state'] == 'normal' for item in display.canvas.items.values())


def test_hiding_russian_keeps_chinese_static(view):
    display, _ = view
    render(display, ru='Я' * 50)
    display.render_entries(
        [SubtitleEntry(1, 'Я' * 50, '短', 0, None, None)],
        show_russian=False, russian_font_size=20, chinese_font_size=34,
    )
    assert display.canvas.items[display._items[0]]['state'] == 'hidden'
    assert display.canvas.items[display._items[1]]['state'] == 'normal'
    assert len(display._lines) == 1


def test_clear_and_destroy_leave_no_animation(view):
    display, _ = view
    render(display, ru='Я' * 50)
    display.render_entries([], show_russian=True, russian_font_size=20, chinese_font_size=34)
    assert display.canvas.timers == {}
    assert display._lines == []
    render(display, ru='Я' * 50)
    display._on_destroy(SimpleNamespace(widget=display.canvas))
    assert display.canvas.timers == {}


def test_outline_preserves_text_and_fits_complete_stroke_bounds(view):
    display, minimums = view
    render(display, text_outline=True)
    assert len(display._outline_items) == 16
    assert all(display.canvas.items[item]['fill'] == 'black' for item in display._outline_items)
    display._on_configure(SimpleNamespace(width=600, height=minimums[-1]))
    for line in display._lines:
        left, top, right, bottom = display.canvas.bbox(line.item)
        assert top >= 1 and bottom + 1 <= minimums[-1]
    render(display, text_outline=False)
    assert display._outline_items == []


def test_zero_text_opacity_hides_both_text_and_outline_in_fallback(view):
    display, _ = view
    render(display, text_outline=True, text_opacity=0)
    assert display._outline_items == []
    assert all(display.canvas.items[item]['state'] == 'hidden' for item in display._items)
    render(display, text_outline=True, text_opacity=1)
    assert len(display._outline_items) == 16
    assert all(display.canvas.items[item]['state'] == 'normal' for item in display._items)
