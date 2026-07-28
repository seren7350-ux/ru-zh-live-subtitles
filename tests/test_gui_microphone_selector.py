from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from live_subtitles.audio.recording import AudioDevice, AudioDeviceError
from live_subtitles.gui.microphone_selector import MicrophoneSelectorModel


def device(
    index: int,
    name: str = "Microphone",
    *,
    channels: int = 1,
    default: bool = False,
) -> AudioDevice:
    return AudioDevice(index, name, channels, 48_000.0, default)


def test_system_default_is_none_and_specific_choices_keep_portaudio_indexes() -> None:
    model = MicrophoneSelectorModel(
        enumerate_devices=lambda: [device(3, default=True), device(8)],
    )
    snapshot = model.refresh()
    assert snapshot.choices[0].label == "System default"
    assert snapshot.choices[0].device_index is None
    assert [choice.device_index for choice in snapshot.choices] == [None, 3, 8]
    assert "[default]" in snapshot.choices[1].label


def test_duplicate_names_remain_distinct_by_index() -> None:
    model = MicrophoneSelectorModel(
        enumerate_devices=lambda: [device(2, "Same name"), device(9, "Same name")]
    )
    snapshot = model.refresh()
    assert snapshot.choices[1].device_index == 2
    assert snapshot.choices[2].device_index == 9
    assert snapshot.choices[1].label.startswith("2 — Same name")
    assert snapshot.choices[2].label.startswith("9 — Same name")


def test_refresh_reenumerates_and_preserves_selection_by_index_after_reorder() -> None:
    calls = 0
    inventories = [
        [device(4), device(7)],
        [device(7), device(4)],
    ]

    def enumerate_devices() -> list[AudioDevice]:
        nonlocal calls
        result = inventories[calls]
        calls += 1
        return result

    model = MicrophoneSelectorModel(7, enumerate_devices=enumerate_devices)
    model.refresh()
    snapshot = model.refresh()
    assert calls == 2
    assert snapshot.selected_index == 7
    assert snapshot.choices[snapshot.selected_position].device_index == 7


def test_disappeared_device_is_unavailable_without_automatic_reselection() -> None:
    inventories = iter([[device(4), device(7)], [device(4)]])
    model = MicrophoneSelectorModel(7, enumerate_devices=lambda: next(inventories))
    model.refresh()
    snapshot = model.refresh()
    assert snapshot.selected_index == 7
    assert not snapshot.choices[snapshot.selected_position].available
    assert snapshot.choices[snapshot.selected_position].device_index == 7
    assert "no longer available" in snapshot.status


def test_empty_input_list_keeps_system_default_and_reports_no_devices() -> None:
    snapshot = MicrophoneSelectorModel(enumerate_devices=lambda: []).refresh()
    assert [choice.device_index for choice in snapshot.choices] == [None]
    assert snapshot.status == "No microphone input devices are available."


def test_query_failure_is_sanitized_and_previous_choices_remain_available() -> None:
    @dataclass
    class Inventory:
        fail: bool = False

        def __call__(self) -> list[AudioDevice]:
            if self.fail:
                raise AudioDeviceError(f"failed at {Path.home() / 'private'}")
            return [device(5)]

    inventory = Inventory()
    model = MicrophoneSelectorModel(5, enumerate_devices=inventory)
    model.refresh()
    inventory.fail = True
    snapshot = model.refresh()
    assert "<home>" in snapshot.status
    assert str(Path.home()) not in snapshot.status
    assert snapshot.query_error_type == "AudioDeviceError"
    assert any(choice.device_index == 5 for choice in snapshot.choices)


def test_snapshot_does_not_poll_devices() -> None:
    calls = 0

    def enumerate_devices() -> list[AudioDevice]:
        nonlocal calls
        calls += 1
        return [device(1)]

    model = MicrophoneSelectorModel(enumerate_devices=enumerate_devices)
    model.refresh()
    model.snapshot()
    model.snapshot()
    assert calls == 1


def test_start_validation_uses_current_default_or_explicit_index() -> None:
    resolved: list[int | None] = []

    def resolve(index: int | None) -> AudioDevice:
        resolved.append(index)
        return device(1, default=True)

    model = MicrophoneSelectorModel(resolve_device=resolve)
    model.validate_selection()
    model.select(8)
    model.validate_selection()
    assert resolved == [None, 8]


def test_invalid_selection_validation_propagates_controlled_audio_error() -> None:
    def reject(_index: int | None) -> AudioDevice:
        raise AudioDeviceError("device unavailable")

    model = MicrophoneSelectorModel(99, resolve_device=reject)
    with pytest.raises(AudioDeviceError, match="unavailable"):
        model.validate_selection()
