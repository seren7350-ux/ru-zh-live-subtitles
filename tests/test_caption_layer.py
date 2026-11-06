from types import SimpleNamespace

import pytest

from live_subtitles.gui import caption_layer


class Window:
    def __init__(self, parent=None):
        self.parent = parent
        self.visible = True
        self.exists = True
        self.window_state = "normal"
        self.values = {"-alpha": 0.25, "-topmost": True}
        self.calls = []
        self.bindings = {}
        self.above_parent = False
        self.native_attached = False
        self.tk = SimpleNamespace(
            call=lambda *args: self.above_parent,
            getboolean=bool,
        )

    def winfo_exists(self):
        return self.exists

    def winfo_ismapped(self):
        return self.visible and self.exists

    def state(self):
        return self.window_state

    def withdraw(self):
        self.calls.append("withdraw")
        self.visible = False
        self.window_state = "withdrawn"

    def deiconify(self):
        assert self.native_attached, "NOACTIVATE and native owner must precede showing captions"
        self.calls.append("deiconify")
        self.visible = True
        self.window_state = "normal"

    def overrideredirect(self, value):
        self.calls.append(("override", value))

    def transient(self, parent):
        self.calls.append(("transient", parent))

    def configure(self, **options):
        self.calls.append(("configure", options))

    def attributes(self, name, value=None):
        if value is None:
            assert name != "-topmost", "Tk's single-attribute GET changes native Z-order"
            return self.values.get(name)
        self.values[name] = value
        self.calls.append((name, value))

    def geometry(self, value):
        self.calls.append(("geometry", value))

    def update_idletasks(self):
        self.calls.append("idle")

    def lift(self, above):
        raise AssertionError("Tk relative lift swaps both popup and owner on Windows")

    def bind(self, sequence, callback):
        self.bindings[sequence] = callback

    def destroy(self):
        self.calls.append("destroy")
        self.exists = self.visible = False


class Canvas:
    def __init__(self, parent, **options):
        self.parent = parent
        self.options = options
        self.items = {}
        self.next_item = 1
        self.repaints = 0

    def pack(self, **options):
        pass

    def create_text(self, x, y, **options):
        item = self.next_item
        self.next_item += 1
        self.items[item] = dict(options, x=x, y=y)
        return item

    def delete(self, tag):
        assert tag == "all"
        self.items.clear()
        self.repaints += 1

    def coords(self, item, x, y):
        self.items[item].update(x=x, y=y)


@pytest.fixture
def surface(monkeypatch):
    calls = []

    def attach(window, root):
        calls.append(("attach", window, root))
        window.native_attached = True

    def detach(window):
        calls.append(("detach", window))
        window.native_attached = False

    def ensure_above_owner(window, root):
        if not window.above_parent:
            calls.append(("position_above", window, root))
            window.above_parent = True

    native = SimpleNamespace(
        attach=attach,
        detach=detach,
        visible=lambda window: window.visible,
        topmost=lambda window: window.values["-topmost"],
        ensure_above_owner=ensure_above_owner,
    )
    monkeypatch.setattr(caption_layer, "_WindowOwner", lambda: native)
    root = Window()
    geometry = [600, 160, -700, 40]
    anchor = SimpleNamespace(
        winfo_ismapped=lambda: True,
        winfo_width=lambda: geometry[0], winfo_height=lambda: geometry[1],
        winfo_rootx=lambda: geometry[2], winfo_rooty=lambda: geometry[3],
    )
    api = SimpleNamespace(Toplevel=Window, Canvas=Canvas, TclError=RuntimeError)
    layer = caption_layer.CaptionLayer(root, anchor, tk_module=api)
    return layer, root, geometry, calls


def line(text="Привет", *, x=10, y=20, outline=False):
    return dict(x=x, y=y, text=text, font=("Segoe UI", 20), anchor="nw",
                fill="white", width=0, outline=outline)


def test_text_alpha_and_outline_are_independent_of_parent_alpha(surface):
    layer, root, _geometry, native = surface
    layer.render([line(outline=True)], opacity=0.0)
    assert layer.window.values["-alpha"] == 0.0
    assert layer.window.values["-transparentcolor"] == caption_layer.COLOR_KEY
    assert root.values["-alpha"] == 0.25 and root.calls == []
    assert len(layer.canvas.items) == 9  # eight stroke offsets and one face
    assert sum(item["fill"] == "black" for item in layer.canvas.items.values()) == 8
    assert ("attach", layer.window, root) in native
    layer.render([line(outline=True)], opacity=0.5)
    assert layer.window.values["-alpha"] == 0.5
    assert root.values["-alpha"] == 0.25


def test_marquee_moves_stroke_with_face_but_leaves_fitting_line_stationary(surface):
    layer, _root, _geometry, _native = surface
    layer.render([line(outline=True), line("短句", x=200, y=80)], opacity=1)
    before = {key: dict(value) for key, value in layer.canvas.items.items()}
    groups = layer._groups
    layer.move_offsets([33, 0])
    for item, _, _ in groups[0]:
        assert layer.canvas.items[item]["x"] == before[item]["x"] - 33
        assert layer.canvas.items[item]["y"] == before[item]["y"]
    for item, _, _ in groups[1]:
        assert layer.canvas.items[item] == before[item]


def test_same_render_keeps_current_marquee_position_without_remap(surface):
    layer, _root, _geometry, _native = surface
    specs = [line(outline=True)]
    layer.render(specs, opacity=1)
    layer.move_offsets([25])
    before = {key: dict(value) for key, value in layer.canvas.items.items()}
    calls = list(layer.window.calls)
    repaints = layer.canvas.repaints
    layer.render(specs, opacity=1)
    assert layer.canvas.items == before
    assert layer.canvas.repaints == repaints
    assert layer.window.calls == calls


def test_caption_is_above_background_after_mapping_and_owner_reordering(surface):
    layer, root, _geometry, native = surface
    layer.render([line()], opacity=1)
    window = layer.window
    assert window.above_parent
    assert native.count(("position_above", window, root)) == 1
    # Restoring or changing the Tk wrapper can put the popup below the owner
    # even while both native windows remain visible and correctly owned.
    window.above_parent = False
    layer.sync_window()
    assert window.above_parent
    assert native.count(("position_above", window, root)) == 2
    layer.sync_window()
    assert native.count(("position_above", window, root)) == 2
    assert root.calls == []


def test_caption_is_native_owned_popup_and_never_tk_transient(surface):
    layer, root, _geometry, native = surface
    layer.render([line()], opacity=1)
    window = layer.window
    assert ("override", True) in window.calls
    assert not any(isinstance(call, tuple) and call[0] == "transient" for call in window.calls)
    # Window.deiconify asserts native ownership already exists at show time.
    assert window.native_attached and "deiconify" in window.calls
    assert ("attach", window, root) in native


def test_topmost_tracking_never_uses_tk_getter_or_reorders_unchanged_surface(surface):
    layer, root, _geometry, native = surface
    layer.render([line()], opacity=1)
    window = layer.window
    root.values["-topmost"] = False
    layer.sync_window()
    assert window.values["-topmost"] is False
    assert window.calls.count(("-topmost", False)) == 1
    before = list(window.calls)
    reorders = native.count(("position_above", window, root))
    for _ in range(20):
        layer.sync_window()
    assert window.calls == before
    assert native.count(("position_above", window, root)) == reorders
    assert root.calls == []


def test_empty_captions_and_minimized_parent_hide_surface_until_restore(surface):
    layer, root, _geometry, _native = surface
    layer.render([line()], opacity=1)
    window = layer.window
    root.window_state = "iconic"
    layer.sync_window()
    assert window.state() == "withdrawn"
    root.window_state = "normal"
    layer.sync_window()
    assert window.state() == "normal" and layer.window is window
    layer.render([], opacity=1)
    assert window.state() == "withdrawn" and layer.canvas.items == {}
    layer.sync_window()
    assert window.state() == "withdrawn"


def test_borderless_transition_detaches_and_suspends_until_explicit_resume(surface):
    layer, root, geometry, native = surface
    layer.render([line()], opacity=1)
    window = layer.window
    layer.prepare_window_change()
    assert native[-1] == ("detach", window)
    assert window.state() == "withdrawn"
    native.clear()
    geometry[2] = -620
    layer.render([line("Changed while switching")], opacity=0.5)
    layer.sync_window()
    assert window.state() == "withdrawn" and native == []
    layer.sync_window(resume=True)
    assert native and all(call == ("attach", window, root) for call in native)
    assert window.state() == "normal"
    assert ("geometry", "600x160+-620+40") in window.calls


def test_native_hidden_popup_restores_even_when_tk_state_is_normal(surface):
    layer, root, _geometry, _native = surface
    layer.render([line()], opacity=1)
    window = layer.window
    window.visible = False  # Windows hides owned popups when the owner minimizes.
    assert window.state() == "normal"
    calls = len(window.calls)
    layer.sync_window()
    assert window.visible and window.state() == "normal"
    assert "deiconify" in window.calls[calls:]
    assert root.calls == []


def test_caption_pointer_bindings_survive_native_surface_recreation(surface):
    layer, _root, _geometry, _native = surface
    received = []
    handler = received.append
    layer.set_pointer_handlers({"<ButtonPress-1>": handler})
    layer.render([line()], opacity=1)
    previous = layer.window
    previous.destroy()
    layer.sync_window()
    assert layer.window is not previous
    event = object()
    layer.window.bindings["<ButtonPress-1>"](event)
    assert received == [event]
    assert list(layer.canvas.items.values())[0]["text"] == "Привет"


def test_close_destroys_owned_surface_and_never_recreates_it(surface):
    layer, _root, _geometry, native = surface
    layer.render([line(outline=True)], opacity=1)
    window = layer.window
    layer.close()
    layer.close()
    assert window.calls.count("destroy") == 1
    native.clear()
    layer.render([line("Later")], opacity=1)
    layer.sync_window(resume=True)
    layer.move_offsets([50])
    assert layer.window is None and layer.canvas is None
    assert native == []


@pytest.fixture
def native_owner(monkeypatch):
    """Exercise the native decisions without loading user32 or creating windows."""
    owner = caption_layer._WindowOwner.__new__(caption_layer._WindowOwner)
    window, root = SimpleNamespace(hwnd=101), SimpleNamespace(hwnd=202)
    styles = {
        (window.hwnd, -16): 0x80000000,  # WS_POPUP
        (window.hwnd, -20): 0x00040008,  # APPWINDOW | TOPMOST before attachment
        (root.hwnd, -20): 0x00000008,
    }
    owners = {}
    previous = {}
    visible = {}
    calls = []
    reads = []
    owner.wrapper = lambda widget: widget.hwnd

    def get_style(hwnd, index):
        reads.append((hwnd, index))
        return styles[(hwnd, index)]

    def set_style(hwnd, index, value):
        calls.append(("style", hwnd, index, value))
        old = styles[(hwnd, index)]
        styles[(hwnd, index)] = value
        return old

    def get_window(hwnd, relationship):
        if relationship == 4:  # GW_OWNER
            return owners.get(hwnd, 0)
        assert relationship == 3  # GW_HWNDPREV
        return previous.get(hwnd, 0)

    def set_owner(hwnd, index, value):
        assert index == -8  # GWLP_HWNDPARENT
        calls.append(("owner", hwnd, index, value))
        old = owners.get(hwnd, 0)
        owners[hwnd] = value
        return old

    def set_position(*args):
        calls.append(("position", *args))
        hwnd, insert_after = args[:2]
        old_previous = previous.get(hwnd, 0)
        for other, above in tuple(previous.items()):
            if above == hwnd:
                previous[other] = old_previous
        immediately_below = next(
            (other for other, above in previous.items()
             if other != hwnd and above == insert_after), None,
        )
        previous[hwnd] = insert_after
        if immediately_below is not None:
            previous[immediately_below] = hwnd
        return True

    owner.get_style = get_style
    owner.set_style = set_style
    owner.get_owner = get_window
    owner.set_owner = set_owner
    owner.set_position = set_position
    owner.is_visible = lambda hwnd: visible.get(hwnd, True)
    owner._identity = None
    monkeypatch.setattr(caption_layer.ctypes, "set_last_error", lambda value: None, raising=False)
    monkeypatch.setattr(caption_layer.ctypes, "get_last_error", lambda: 0, raising=False)
    return SimpleNamespace(
        api=owner, window=window, root=root, styles=styles, owners=owners,
        previous=previous, visible=visible, calls=calls, reads=reads,
    )


@pytest.mark.parametrize("window_style", [0x40000000, 0xC0000000, 0])
def test_native_attachment_rejects_child_or_non_popup_before_any_mutation(native_owner, window_style):
    native = native_owner
    native.styles[(native.window.hwnd, -16)] = window_style
    with pytest.raises(RuntimeError, match="top-level popup"):
        native.api.attach(native.window, native.root)
    assert native.calls == []
    assert native.owners == {}


def test_native_attachment_keeps_caption_out_of_taskbar_and_repairs_owner_only_when_needed(native_owner):
    native = native_owner
    native.api.attach(native.window, native.root)
    flags = native.styles[(native.window.hwnd, -20)]
    assert flags & 0x80  # WS_EX_TOOLWINDOW
    assert flags & 0x08000000  # WS_EX_NOACTIVATE
    assert flags & 0x8  # preserve WS_EX_TOPMOST
    assert not flags & 0x40000  # no WS_EX_APPWINDOW
    assert native.owners[native.window.hwnd] == native.root.hwnd
    assert all(call[1] == native.window.hwnd for call in native.calls)
    native.calls.clear()
    native.api.attach(native.window, native.root)
    assert native.calls == []
    # Mapping may reset native ownership while preserving HWND identity.
    native.owners[native.window.hwnd] = 0
    native.api.attach(native.window, native.root)
    assert native.calls == [("owner", native.window.hwnd, -8, native.root.hwnd)]


@pytest.mark.parametrize("topmost", [False, True])
def test_native_topmost_query_reads_flags_without_mutating_any_window(native_owner, topmost):
    native = native_owner
    native.styles[(native.root.hwnd, -20)] = 0x80000 | (0x8 if topmost else 0)
    assert native.api.topmost(native.root) is topmost
    assert native.reads == [(native.root.hwnd, -20)]
    assert native.calls == []


@pytest.mark.parametrize("intervening", [False, True])
def test_native_order_leaves_caption_and_settings_untouched_when_already_above(native_owner, intervening):
    native = native_owner
    settings = 303
    unrelated = 404
    native.owners[settings] = native.root.hwnd
    native.previous[native.root.hwnd] = unrelated if intervening else native.window.hwnd
    if intervening:
        native.previous[unrelated] = native.window.hwnd
    native.previous[native.window.hwnd] = settings
    for _ in range(20):
        native.api.ensure_above_owner(native.window, native.root)
    assert native.calls == []


@pytest.mark.parametrize("predecessor", [0, 303])
def test_native_order_repairs_only_caption_without_activating_or_swapping_owner(native_owner, predecessor):
    native = native_owner
    # The subtitle is below its owner; any Settings popup above the root stays
    # above the caption after inserting the caption immediately before root.
    native.previous[native.root.hwnd] = predecessor
    native.previous[native.window.hwnd] = native.root.hwnd
    native.api.ensure_above_owner(native.window, native.root)
    assert len(native.calls) == 1
    name, hwnd, insert_after, x, y, width, height, flags = native.calls[0]
    assert (name, hwnd, insert_after) == ("position", native.window.hwnd, predecessor)
    assert (x, y, width, height) == (0, 0, 0, 0)
    assert flags & 0x1 and flags & 0x2  # SWP_NOSIZE | SWP_NOMOVE
    assert flags & 0x10 and flags & 0x200  # SWP_NOACTIVATE | SWP_NOOWNERZORDER
    assert not flags & 0x4  # a Z-order repair must not use SWP_NOZORDER


@pytest.mark.parametrize("dialog_count", [1, 2])
def test_native_order_puts_remapped_caption_below_existing_dialogs_once(native_owner, dialog_count):
    native = native_owner
    lowest_dialog, higher_dialog = 303, 404
    native.owners[lowest_dialog] = native.root.hwnd
    native.previous[native.root.hwnd] = lowest_dialog
    if dialog_count == 2:
        native.owners[higher_dialog] = native.root.hwnd
        native.previous[lowest_dialog] = higher_dialog
        native.previous[higher_dialog] = native.window.hwnd
    else:
        native.previous[lowest_dialog] = native.window.hwnd
    native.previous[native.window.hwnd] = 0
    # Clear hides the caption; mapping the next subtitle may put it over
    # Settings again. Reinsert below the lowest visible owned dialog.
    native.api.ensure_above_owner(native.window, native.root)
    assert len(native.calls) == 1
    assert native.calls[0][:3] == ("position", native.window.hwnd, lowest_dialog)
    assert native.previous[native.root.hwnd] == native.window.hwnd
    assert native.previous[native.window.hwnd] == lowest_dialog
    if dialog_count == 2:
        assert native.previous[lowest_dialog] == higher_dialog
    for _ in range(20):
        native.api.ensure_above_owner(native.window, native.root)
    assert len(native.calls) == 1


@pytest.mark.parametrize(("same_owner", "is_visible"), [(True, False), (False, True), (False, False)])
def test_native_order_ignores_hidden_or_unrelated_windows(native_owner, same_owner, is_visible):
    native = native_owner
    other = 303
    native.owners[other] = native.root.hwnd if same_owner else 999
    native.visible[other] = is_visible
    native.previous[native.root.hwnd] = other
    native.previous[other] = native.window.hwnd
    for _ in range(20):
        native.api.ensure_above_owner(native.window, native.root)
    assert native.calls == []
