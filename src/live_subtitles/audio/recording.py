"""Input-device discovery and bounded PCM WAV recording."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


class AudioDeviceError(RuntimeError):
    """Raised when audio input devices cannot be queried or selected."""


class RecordingError(RuntimeError):
    """Raised when audio capture or WAV writing fails."""


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_default: bool


@dataclass(frozen=True)
class RecordingResult:
    path: Path
    device: AudioDevice
    frames: int
    sample_rate: int
    size_bytes: int


def _sounddevice() -> Any:
    try:
        import sounddevice
    except Exception as exc:
        raise AudioDeviceError(f"sounddevice is unavailable: {exc}") from exc
    return sounddevice


def _default_input_index(sd: Any) -> int | None:
    value = sd.default.device
    if not isinstance(value, (int, float, str, bytes)):
        try:
            value = value[0]
        except (IndexError, KeyError, TypeError):
            return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def list_input_devices(sd: Any | None = None) -> list[AudioDevice]:
    """Return only devices that expose at least one input channel."""

    sd = sd or _sounddevice()
    try:
        raw_devices = list(sd.query_devices())
    except Exception as exc:
        raise AudioDeviceError(f"Unable to query audio input devices: {exc}") from exc

    default_index = _default_input_index(sd)
    devices: list[AudioDevice] = []
    for index, raw in enumerate(raw_devices):
        channels = int(raw.get("max_input_channels", 0))
        if channels <= 0:
            continue
        devices.append(
            AudioDevice(
                index=index,
                name=str(raw.get("name", f"Device {index}")),
                max_input_channels=channels,
                default_sample_rate=float(raw.get("default_samplerate", 0.0)),
                is_default=index == default_index,
            )
        )
    return devices


def select_input_device(device_index: int | None, sd: Any | None = None) -> AudioDevice:
    sd = sd or _sounddevice()
    devices = list_input_devices(sd)
    if not devices:
        raise AudioDeviceError("No audio input devices are available.")
    if device_index is None:
        default = next((device for device in devices if device.is_default), None)
        if default is None:
            raise AudioDeviceError("No default audio input device is configured; pass --device with a listed input device number.")
        return default
    selected = next((device for device in devices if device.index == device_index), None)
    if selected is None:
        raise AudioDeviceError(f"Input device {device_index} does not exist or has no input channels.")
    return selected


def record_wav(
    output: Path,
    *,
    seconds: float = 8.0,
    sample_rate: int = 16_000,
    device_index: int | None = None,
    sd: Any | None = None,
) -> RecordingResult:
    """Record bounded float32 mono audio and save it as PCM16 WAV."""

    if seconds <= 0:
        raise RecordingError("Recording duration must be greater than 0 seconds.")
    if seconds > 30:
        raise RecordingError("Recording duration must not exceed 30 seconds.")
    if sample_rate <= 0:
        raise RecordingError("Sample rate must be greater than 0 Hz.")

    sd = sd or _sounddevice()
    selected = select_input_device(device_index, sd)
    frames = round(seconds * sample_rate)
    try:
        samples = sd.rec(
            frames,
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=selected.index,
        )
        sd.wait()
    except Exception as exc:
        raise RecordingError(
            "Recording failed; check microphone permission and whether the input device is busy: "
            f"{exc}"
        ) from exc

    try:
        mono = np.asarray(samples, dtype=np.float32).reshape(-1)
        clipped = np.clip(mono, -1.0, 1.0)
        pcm16 = (clipped * np.iinfo(np.int16).max).astype("<i2")
        resolved = output.expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(resolved), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm16.tobytes())
    except (OSError, ValueError, wave.Error) as exc:
        raise RecordingError(f"Unable to write PCM WAV file {output}: {exc}") from exc

    return RecordingResult(
        path=resolved,
        device=selected,
        frames=len(pcm16),
        sample_rate=sample_rate,
        size_bytes=resolved.stat().st_size,
    )
