from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from live_subtitles.gui import windows_taskbar as win


@pytest.fixture
def taskbar(monkeypatch):
    # Exercise the shell contract on CI without creating a real desktop window.
    monkeypatch.setattr(win.ctypes, "set_last_error", lambda error: None, raising=False)
    bar = win.WindowsTaskbar.__new__(win.WindowsTaskbar)
    bar._user32 = Mock()
    bar._user32.GetAncestor.return_value = 123
    bar._user32.GetWindowLongW.side_effect = lambda hwnd, index: {
        win.GWL_STYLE: win.WS_MINIMIZEBOX | win.WS_SYSMENU,
        win.GWL_EXSTYLE: win.WS_EX_TOOLWINDOW,
    }[index]
    bar._user32.IsWindowVisible.return_value = True
    bar._user32.IsIconic.return_value = False
    return bar


ROOT = SimpleNamespace(winfo_id=lambda: 42)


def test_registers_current_wrapper_and_keeps_layered_topmost_style(taskbar):
    api = taskbar._user32
    layered_topmost = 0x80000 | 0x8
    api.GetAncestor.side_effect = [123, 456]
    api.GetWindowLongW.side_effect = lambda hwnd, index: (
        win.WS_MINIMIZEBOX | win.WS_SYSMENU if index == win.GWL_STYLE
        else layered_topmost | (win.WS_EX_TOOLWINDOW if hwnd == 123 else win.WS_EX_APPWINDOW)
    )
    taskbar.ensure_button(ROOT)
    taskbar.ensure_button(ROOT)

    assert api.GetAncestor.call_args_list == [call(42, win.GA_ROOT)] * 2
    assert api.GetWindowLongW.call_args_list == [
        call(123, win.GWL_STYLE), call(123, win.GWL_EXSTYLE),
        call(456, win.GWL_STYLE), call(456, win.GWL_EXSTYLE),
    ]
    api.SetWindowLongW.assert_called_once_with(
        123, win.GWL_EXSTYLE, layered_topmost | win.WS_EX_APPWINDOW
    )
    assert api.SetWindowPos.call_args_list == [
        call(123, None, 0, 0, 0, 0, win.KEEP_PLACEMENT | win.SWP_HIDEWINDOW),
        call(123, None, 0, 0, 0, 0,
             win.KEEP_PLACEMENT | win.SWP_SHOWWINDOW | win.SWP_FRAMECHANGED),
    ]


@pytest.mark.parametrize(("visible", "iconic"), [(False, False), (True, True)])
def test_registering_hidden_or_minimized_window_preserves_visibility(taskbar, visible, iconic):
    api = taskbar._user32
    api.IsWindowVisible.return_value = visible
    api.IsIconic.return_value = iconic
    taskbar.ensure_button(ROOT)
    api.SetWindowPos.assert_called_once_with(
        123, None, 0, 0, 0, 0, win.KEEP_PLACEMENT | win.SWP_FRAMECHANGED
    )


@pytest.mark.parametrize("native_style", [0x96000008, 0xB6000008])
def test_borderless_wrapper_supports_shell_minimize_without_adding_frame(taskbar, native_style):
    api = taskbar._user32
    # GetWindowLongW returns a signed LONG, including for a popup/minimized HWND.
    native_style -= 1 << 32
    existing_exstyle = 0x80000 | 0x8 | win.WS_EX_APPWINDOW
    api.GetWindowLongW.side_effect = lambda hwnd, index: {
        win.GWL_STYLE: native_style,
        win.GWL_EXSTYLE: existing_exstyle,
    }[index]

    taskbar.ensure_button(ROOT)

    # Even an already registered taskbar window needs the native minimize style.
    # Preserve popup, visibility, minimize state and all other native style bits;
    # do not add WS_CAPTION or WS_THICKFRAME to the borderless window.
    api.SetWindowLongW.assert_called_once_with(
        123, win.GWL_STYLE, native_style | win.WS_MINIMIZEBOX | win.WS_SYSMENU
    )
    api.SetWindowPos.assert_called_once_with(
        123, None, 0, 0, 0, 0, win.KEEP_PLACEMENT | win.SWP_FRAMECHANGED
    )
    api.ShowWindow.assert_not_called()


def test_decorated_wrapper_keeps_existing_native_and_extended_styles(taskbar):
    api = taskbar._user32
    api.GetWindowLongW.side_effect = lambda hwnd, index: {
        win.GWL_STYLE: 0x16CF0008,
        win.GWL_EXSTYLE: 0xC0108,
    }[index]

    taskbar.ensure_button(ROOT)

    api.SetWindowLongW.assert_not_called()
    api.SetWindowPos.assert_not_called()


@pytest.mark.parametrize("iconic", [False, True])
def test_activation_restores_only_native_minimized_window(taskbar, iconic):
    api = taskbar._user32
    api.IsIconic.return_value = iconic
    api.SetForegroundWindow.return_value = True
    taskbar.activate(ROOT)
    expected = [call.ShowWindow(123, win.SW_RESTORE)] if iconic else []
    assert api.method_calls == [
        call.GetAncestor(42, win.GA_ROOT), call.IsIconic(123),
        *expected, call.SetForegroundWindow(123),
    ]


def test_denied_foreground_request_flashes_existing_button(taskbar):
    api = taskbar._user32
    api.SetForegroundWindow.return_value = False
    taskbar.activate(ROOT)
    flash = api.FlashWindowEx.call_args.args[0]._obj
    assert (flash.hwnd, flash.dwFlags, flash.uCount) == (123, win.FLASHW_TRAY, 3)
