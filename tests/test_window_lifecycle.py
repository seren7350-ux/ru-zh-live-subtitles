"""Exercise deferred lifecycle scripts with Tcl only; never map a Tk window."""

from types import SimpleNamespace

import pytest

from live_subtitles.gui.windows_taskbar import bind_window_lifecycle


@pytest.fixture
def root():
    tkinter = pytest.importorskip("tkinter")
    interpreter = tkinter.Tcl()

    class Root:
        def __init__(self):
            self.tk = interpreter.tk
            self.register = interpreter.register
            self.bindings = {}
            self.exists = True

        def __str__(self):
            return "."

        def bind(self, sequence, script, add=None):
            # Tkinter passes a string script straight through, ignoring add.
            # Tk itself appends only when the script has a literal '+' prefix.
            if script.startswith("+"):
                self.bindings[sequence] = self.bindings.get(sequence, "") + "\n" + script[1:]
            else:
                self.bindings[sequence] = script

        def winfo_exists(self):
            return self.exists

        def fire(self, sequence, widget="."):
            self.tk.eval(self.bindings[sequence].replace("%W", widget))

        def idle(self):
            self.tk.eval("update idletasks")

    instance = Root()
    yield instance
    for item in instance.tk.splitlist(instance.tk.call("after", "info")):
        instance.tk.call("after", "cancel", item)
    # Tk.deletecommand bookkeeping releases every registered Python closure.
    for command in tuple(interpreter._tclCommands or ()):
        interpreter.deletecommand(command)


def test_native_event_does_not_call_python_until_tcl_idle(root):
    calls = []
    bind_window_lifecycle(root, "<Unmap>", calls.append)
    root.fire("<Unmap>")
    assert calls == []
    root.idle()
    assert len(calls) == 1 and calls[0].widget is root
    assert root.tk.call("after", "info") == ""


def test_configure_burst_is_coalesced_and_child_bindtag_events_ignored(root):
    received = []
    root.width = 400
    bind_window_lifecycle(root, "<Configure>", lambda event: received.append(event.widget.width))
    root.fire("<Configure>", ".child")
    assert root.tk.call("after", "info") == ""
    for width in range(401, 501):
        root.width = width
        root.fire("<Configure>")
    assert len(root.tk.splitlist(root.tk.call("after", "info"))) == 1
    root.idle()
    assert received == [500]


def test_destroy_cancels_all_pending_lifecycle_callbacks_and_variables(root):
    received = []
    for sequence in ("<Map>", "<Unmap>", "<FocusIn>", "<FocusOut>", "<Configure>"):
        bind_window_lifecycle(root, sequence, received.append)
        root.fire(sequence)
    assert len(root.tk.splitlist(root.tk.call("after", "info"))) == 5
    root.fire("<Destroy>", ".child")
    assert len(root.tk.splitlist(root.tk.call("after", "info"))) == 5
    root.fire("<Destroy>")
    root.exists = False
    root.idle()
    assert received == []
    assert root.tk.call("after", "info") == ""
    assert root.tk.call("info", "vars", "::*_pending") == ""


def test_lifecycle_binding_preserves_existing_python_destroy_cleanup(root):
    destroyed = []
    animated = []
    animation_command = root.register(lambda: animated.append(True))
    animation_timer = root.tk.call("after", "idle", animation_command)

    def stop_animation_and_close_surface():
        root.tk.call("after", "cancel", animation_timer)
        destroyed.append(True)

    existing = root.register(stop_animation_and_close_surface)
    root.bind("<Destroy>", existing)
    bind_window_lifecycle(root, "<Map>", lambda event: animated.append("late map"))
    root.fire("<Map>")
    root.fire("<Destroy>")
    root.exists = False
    root.idle()
    assert destroyed == [True]
    assert animated == []
    assert root.tk.call("after", "info") == ""


def test_dispatch_does_not_touch_destroyed_root_when_destroy_event_was_missed(root):
    calls = []
    bind_window_lifecycle(root, "<Map>", calls.append)
    root.fire("<Map>")
    root.exists = False
    root.idle()
    assert calls == []


def test_simple_widget_double_keeps_python_binding_contract():
    bindings = {}
    root = SimpleNamespace(bind=lambda sequence, callback: bindings.update({sequence: callback}))
    callback = lambda event: None
    bind_window_lifecycle(root, "<Map>", callback)
    assert bindings == {"<Map>": callback}
