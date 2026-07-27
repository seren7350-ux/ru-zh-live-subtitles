"""Strict mono PCM16 WAV writing shared by recording and live pipelines."""

from __future__ import annotations

import uuid
import wave
from pathlib import Path

import numpy as np


def write_pcm16_mono_wav(
    path: Path,
    samples: np.ndarray,
    *,
    sample_rate: int = 16_000,
    atomic: bool = False,
) -> Path:
    """Write finite float samples as strict mono little-endian PCM16 WAV."""

    if sample_rate <= 0:
        raise ValueError("Sample rate must be greater than zero.")
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if not np.isfinite(values).all():
        raise ValueError("WAV samples must be finite.")
    pcm = np.rint(np.clip(values, -1.0, 32767.0 / 32768.0) * 32768.0).astype("<i2")
    destination = (
        resolved.with_name(f".{resolved.name}.{uuid.uuid4().hex}.tmp")
        if atomic
        else resolved
    )
    try:
        with wave.open(str(destination), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())
        if atomic:
            destination.replace(resolved)
    except Exception:
        if atomic:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return resolved
