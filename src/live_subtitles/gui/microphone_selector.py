"""No-Tk microphone selection state for the live subtitle settings panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..audio.recording import (
    AudioDevice,
    AudioDeviceError,
    list_input_devices,
    select_input_device,
)
from .controller import sanitize_message


@dataclass(frozen=True)
class MicrophoneChoice:
    """One display choice whose identity is always a PortAudio device index."""

    device_index: int | None
    label: str
    available: bool = True


@dataclass(frozen=True)
class MicrophoneSelectorSnapshot:
    """Immutable view data consumed by the Tk settings panel."""

    choices: tuple[MicrophoneChoice, ...]
    selected_index: int | None
    selected_position: int
    status: str
    query_error_type: str | None = None


def format_device_label(device: AudioDevice) -> str:
    """Format a readable label without using it as device identity."""

    channels = "channel" if device.max_input_channels == 1 else "channels"
    rate = round(device.default_sample_rate)
    default = " [default]" if device.is_default else ""
    return (
        f"{device.index} — {device.name} "
        f"({device.max_input_channels} {channels}, {rate} Hz){default}"
    )


class MicrophoneSelectorModel:
    """Manage process-local input selection without importing or calling Tk."""

    def __init__(
        self,
        selected_index: int | None = None,
        *,
        enumerate_devices: Callable[[], list[AudioDevice]] = list_input_devices,
        resolve_device: Callable[[int | None], AudioDevice] = select_input_device,
    ) -> None:
        self.selected_index = selected_index
        self._enumerate_devices = enumerate_devices
        self._resolve_device = resolve_device
        self._devices: tuple[AudioDevice, ...] = ()
        self._query_error: str | None = None
        self._query_error_type: str | None = None
        self._has_refreshed = False

    @property
    def has_refreshed(self) -> bool:
        return self._has_refreshed

    def select(self, device_index: int | None) -> MicrophoneSelectorSnapshot:
        """Select by index only; callers decide when mutation is permitted."""

        self.selected_index = device_index
        return self.snapshot()

    def refresh(self) -> MicrophoneSelectorSnapshot:
        """Enumerate once on demand while preserving a selection by index."""

        self._has_refreshed = True
        try:
            self._devices = tuple(self._enumerate_devices())
        except AudioDeviceError as exc:
            self._query_error = sanitize_message(exc)
            self._query_error_type = type(exc).__name__
        else:
            self._query_error = None
            self._query_error_type = None
        return self.snapshot()

    def validate_selection(self) -> AudioDevice:
        """Resolve the current choice immediately before starting a session."""

        return self._resolve_device(self.selected_index)

    def snapshot(self) -> MicrophoneSelectorSnapshot:
        choices = [MicrophoneChoice(None, "System default")]
        choices.extend(
            MicrophoneChoice(device.index, format_device_label(device))
            for device in self._devices
        )

        selected_position = next(
            (
                position
                for position, choice in enumerate(choices)
                if choice.device_index == self.selected_index
            ),
            -1,
        )
        selected_available = selected_position >= 0
        if self.selected_index is not None and not selected_available:
            choices.append(
                MicrophoneChoice(
                    self.selected_index,
                    f"{self.selected_index} — unavailable",
                    available=False,
                )
            )
            selected_position = len(choices) - 1

        if self._query_error is not None:
            status = f"Unable to query microphone devices: {self._query_error}"
        elif not self._devices:
            status = "No microphone input devices are available."
        elif self.selected_index is not None and not selected_available:
            status = (
                "Selected microphone is no longer available. "
                "Refresh and choose another device."
            )
        else:
            selected_label = choices[selected_position].label
            status = f"Selected for next session: {selected_label}"

        return MicrophoneSelectorSnapshot(
            choices=tuple(choices),
            selected_index=self.selected_index,
            selected_position=selected_position,
            status=status,
            query_error_type=self._query_error_type,
        )
