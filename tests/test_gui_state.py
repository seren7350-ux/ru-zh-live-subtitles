from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from live_subtitles.gui.events import PreparingEvent
from live_subtitles.gui.state import SubtitleEntry, SubtitleViewState


def entry(index: int) -> SubtitleEntry:
    return SubtitleEntry(index, f"ru-{index}", f"zh-{index}", float(index), 0.1, 0.2)


def test_event_is_immutable() -> None:
    event = PreparingEvent("preparing", 1.0)
    with pytest.raises(FrozenInstanceError):
        event.message = "changed"  # type: ignore[misc]


def test_state_defaults_and_status_flags() -> None:
    state = SubtitleViewState()
    assert state.history_lines == 20
    assert state.display_lines == 2
    assert state.opacity == 0.88
    assert state.show_russian and state.topmost and state.borderless
    assert state.position == "bottom"
    assert not state.settings_visible
    assert not state.stopping
    assert not state.listening and not state.preparing
    state.begin_session()
    assert state.preparing and not state.listening
    state.set_status("Listening... microphone")
    assert state.listening and not state.preparing


def test_history_is_bounded_and_only_latest_two_are_visible() -> None:
    state = SubtitleViewState(history_lines=3)
    for index in range(1, 6):
        assert state.add_subtitle(entry(index))
    assert [item.index for item in state.entries] == [3, 4, 5]
    assert [item.index for item in state.visible_entries] == [4, 5]


def test_duplicate_index_is_ignored() -> None:
    state = SubtitleViewState()
    assert state.add_subtitle(entry(1))
    assert not state.add_subtitle(entry(1))
    assert len(state.entries) == 1


def test_clear_removes_only_in_memory_text_and_error() -> None:
    state = SubtitleViewState()
    state.add_subtitle(entry(1))
    state.set_segment_error("failure")
    state.clear()
    assert state.entries == ()
    assert state.latest_error == ""
    assert state.status == "Ready"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"history_lines": 0}, "History"),
        ({"history_lines": 101}, "History"),
        ({"display_lines": 0}, "Display"),
        ({"opacity": 0.49}, "Opacity"),
        ({"opacity": 1.01}, "Opacity"),
        ({"chinese_font_size": 15}, "Chinese"),
        ({"russian_font_size": 49}, "Russian"),
    ],
)
def test_state_bounds(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SubtitleViewState(**kwargs)  # type: ignore[arg-type]


def test_segment_error_does_not_replace_successful_subtitle() -> None:
    state = SubtitleViewState()
    state.add_subtitle(entry(1))
    state.set_segment_error("Segment 2: translation failed")
    assert state.entries == (entry(1),)
    assert "translation failed" in state.latest_error


@pytest.mark.parametrize("name", ["top", "bottom", "floating"])
def test_position_state_accepts_presets(name: str) -> None:
    state = SubtitleViewState()
    state.set_position(name)
    assert state.position == name
